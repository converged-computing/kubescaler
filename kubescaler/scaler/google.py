# Copyright 2023-2024 Lawrence Livermore National Security, LLC and other
# HPCIC DevTools Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (MIT)

import base64
import sys
import tempfile
import time

from kubernetes import client as kubernetes_client

from kubescaler.cluster import Cluster
from kubescaler.decorators import retry, timed

try:
    import google.auth
    import google.auth.transport.requests
    from google.api_core.exceptions import NotFound
    from google.cloud import container_v1
except ImportError:
    sys.exit("Please pip install kubescaler[google]")


class GKECluster(Cluster):
    """
    A scaler for a Google Kubernetes Engine (GKE) cluster
    """

    default_region = "us-central1"

    def __init__(
        self,
        project,
        default_pool_name="default-pool",
        # Set the zone for a more scoped request
        zone="us-central1-a",
        spot=False,
        max_vcpu=8,
        max_memory=32,
        # Initial labels for the default cluster
        labels=None,
        scaling_profile=0,
        **kwargs,
    ):
        """
        A simple class to control creating a cluster
        """
        super().__init__(**kwargs)

        # This client we can use to interact with Google Cloud GKE
        # https://github.com/googleapis/python-container/blob/main/google/cloud/container_v1/services/cluster_manager/client.py#L96
        print("⭐️ Creating global cluster manager client...")
        self.client = container_v1.ClusterManagerClient()
        self.project = project
        self.machine_type = self.machine_type or "c2-standard-8"
        self.tags = self.tags or ["kubescaler-cluster"]
        self.default_pool = default_pool_name
        self.configuration = None
        self.scaling_profile = scaling_profile
        self.labels = labels
        self.zone = zone
        self.max_vcpu = max_vcpu
        self.max_memory = max_memory
        self.spot = False

    @timed
    def delete_cluster(self):
        """
        Delete the cluster
        """
        request = container_v1.DeleteClusterRequest(name=self.cluster_name)
        # Make the request, and check until deleted!
        self.client.delete_cluster(request=request)
        self.configuration = None
        self.wait_for_delete()

    @property
    def data(self):
        """
        Combine class data into json object to save
        """
        return {
            "times": self.times,
            "cluster_name": self.cluster_name,
            "name": self.name,
            "machine_type": self.machine_type,
            "region": self.region,
            "zone": self.zone,
            "tags": self.tags,
            "description": self.description,
        }

    def scale_up(self, count, pool_name=None):
        """
        Make a request to scale the cluster
        """
        return self.scale(count, count, count + 1, pool_name=pool_name)

    def scale_down(self, count, pool_name=None):
        """
        Make a request to scale the cluster
        """
        return self.scale(
            count, max(count - 1, self.min_nodes), count, pool_name=pool_name
        )

    def scale(self, count, min_count, max_count, pool_name=None):
        """
        Make a request to scale the cluster
        """
        pool_name = pool_name or self.default_pool
        node_pool_name = f"{self.cluster_name}/nodePools/{pool_name}"

        # Always make the max node count one more than we want
        # I'm not sure if we need to change the policy with the size
        autoscaling = container_v1.NodePoolAutoscaling(
            enabled=True,
            min_node_count=min_count,
            max_node_count=max_count,
        )

        # https://github.com/googleapis/python-container/blob/main/google/cloud/container_v1/types/cluster_service.py#L3884
        request = container_v1.SetNodePoolAutoscalingRequest(
            autoscaling=autoscaling,
            name=node_pool_name,
        )
        self.client.set_node_pool_autoscaling(request=request)

        # This is wrapped in a retry
        self.resize_cluster(count, node_pool_name)

        # wait for it to be running again, will go from reconciling -> running
        return self.wait_for_status(2)

    @retry
    def resize_cluster(self, count, node_pool_name):
        """
        Do the resize of the cluster
        """
        # This is the request that actually changes the size
        request = container_v1.SetNodePoolSizeRequest(
            node_count=count,
            name=node_pool_name,
        )
        return self.client.set_node_pool_size(request=request)

    def get_node_config(self, machine_type=None, spot=False, labels=None):
        """
        Get a node config for a specific machine type, and spot.
        """
        node_config = container_v1.NodeConfig(
            machine_type=machine_type or self.machine_type,
            tags=self.tags,
            spot=spot or self.spot,
            labels=labels,
        )
        print(node_config)
        return node_config

    def get_k8s_client(self):
        """
        Get a client to use to interact with the cluster, either corev1.api
        or the kubernetes api client.

        https://github.com/googleapis/python-container/issues/6
        """
        request = {"name": self.cluster_name}
        response = self.client.get_cluster(request=request)
        creds, projects = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)

        # Save the configuration for advanced users to user later
        if not self.configuration:
            configuration = kubernetes_client.Configuration()
            configuration.host = f"https://{response.endpoint}"
            with tempfile.NamedTemporaryFile(delete=False) as ca_cert:
                ca_cert.write(
                    base64.b64decode(response.master_auth.cluster_ca_certificate)
                )
                configuration.ssl_ca_cert = ca_cert.name
            configuration.api_key_prefix["authorization"] = "Bearer"
            configuration.api_key["authorization"] = creds.token
            self.configuration = configuration

        # This has .api_client for just the api client
        return kubernetes_client.CoreV1Api(self.get_api_client())

    def get_api_client(self):
        return kubernetes_client.ApiClient(self.configuration)

    def get_existing_cluster(self, cluster_name=None):
        """
        Get a cluster after it's been created.
        """
        name = cluster_name or self.cluster_name
        request = container_v1.GetClusterRequest(name=name)
        try:
            return self.client.get_cluster(request=request)
        except NotFound:
            pass

    @timed
    def create_cluster_nodes(
        self,
        name,
        node_count,
        machine_type=None,
        spot=False,
        labels=None,
        threads_per_core=None,
        placement_policy=None,
        tier_1=False,
    ):
        """
        Create a node pool to add to the cluster.

        https://github.com/googleapis/google-cloud-python/blob/min/
        packages/google-cloud-container/google/cloud/container_v1/
        services/cluster_manager/client.py#L3131
        """
        machine_type = machine_type or self.machine_type
        node_config = self.get_node_config(machine_type, spot=spot, labels=labels)

        # The min/max node counts are provided with the NodePoolAutoscaling
        # For now we assume min == max for a constant number of nodes
        autoscaling = container_v1.NodePoolAutoscaling(
            enabled=True,
            min_node_count=node_count,
            max_node_count=node_count,
        )

        node_pool = container_v1.types.NodePool(
            name=name,
            config=node_config,
            initial_node_count=node_count,
            autoscaling=autoscaling,
            # not specifying network_config uses cluster defaults
        )

        # Do we want tier_1 network (expensive)?
        if tier_1:
            tier_1_config = (
                container_v1.types.NodeNetworkConfig.NetworkPerformanceConfig(
                    total_egress_bandwidth_tier=1
                )
            )
            network_config = container_v1.types.NodeNetworkConfig(
                network_performance_config=tier_1_config
            )
            node_pool.network_config = network_config

        # Do we want a placement policy?
        if placement_policy is not None:
            policy = container_v1.types.NodePool.PlacementPolicy(type=placement_policy)
            node_pool.placement_policy = policy

        # Do we want to set threads per core (yes, probably)
        if threads_per_core is not None:
            features = container_v1.types.AdvancedMachineFeatures(
                threads_per_core=threads_per_core
            )
            node_pool.config.advanced_machine_features = features

        request = container_v1.CreateNodePoolRequest(
            parent=self.cluster_name,
            node_pool=node_pool,
        )

        # Most instances don't allow COMPACT
        try:
            response = self.client.create_node_pool(request=request)
        except Exception as e:
            if placement_policy is not None:
                return self.create_cluster_nodes(
                    name=name,
                    node_count=node_count,
                    machine_type=machine_type,
                    spot=spot,
                    labels=labels,
                    threads_per_core=threads_per_core,
                    tier_1=tier_1,
                )
            raise (e)

        print(response)
        print(f"⏱️   Waiting for node pool {name} to be ready...")
        return self.wait_for_status(2)

    @property
    def location(self):
        """
        Return the preferred location. If you ask for resources for a region,
        you often get the N amount in each ZONE which is not desired.
        """
        return self.zone or self.region

    @timed
    def delete_nodegroup(self, name=None):
        """
        Delete a named node group.
        """
        node_pool = name or self.default_pool
        name = f"{self.cluster_name}/nodePools/{node_pool}"
        request = container_v1.DeleteNodePoolRequest(name=name)
        self.client.delete_node_pool(request=request)
        return self.wait_for_status(2)

    def get_cluster(self, node_pools=None, scaling_profile=None):
        """
        Get the cluster proto with our defaults
        """
        if scaling_profile is None:
            scaling_profile = self.scaling_profile
        if scaling_profile not in [0, 1, 2]:
            raise ValueError("Scaling profile must be one of 0,1,2")

        # autoprovisioning node defaults. Note that upgrade settings
        # default to a surge strategy, max surge 1 and nodes unavailable 2
        # I tried setting auto_upgrade and auto_repair to False but that
        # must be the default, they don't show up

        # Design our initial cluster!
        # Autoscaling - try optimizing
        # PROFILE_UNSPECIFIED = 0
        # OPTIMIZE_UTILIZATION = 1
        # BALANCED = 2
        autoscaling_profile = container_v1.ClusterAutoscaling.AutoscalingProfile(
            scaling_profile
        )

        # These are only intended if you want GKE to make new node pools for you
        # I highly do not recommend this, I've never had this result in desired
        # behavior.
        # https://cloud.google.com/compute/docs/compute-optimized-machines
        # resource_limits = [
        #    container_v1.ResourceLimit(
        #        resource_type="cpu",
        #        minimum=0,
        #        maximum=self.max_vcpu * self.node_count,
        #    ),
        #    container_v1.ResourceLimit(
        #        resource_type="memory",
        #        minimum=0,
        #        maximum=self.max_memory * self.node_count,
        #    ),
        # ]

        # When autoprovisioning is enabled the cluster explodes into much
        # larger sizes than you want.
        cluster_autoscaling = container_v1.ClusterAutoscaling(
            enable_node_autoprovisioning=False,
            autoscaling_profile=autoscaling_profile,
            # These two fields are only for node autoprovisioning
            # autoprovisioning_locations=[self.location],
            # resource_limits=resource_limits,
        )

        # vertical_pod_autoscaling (google.cloud.container_v1.types.VerticalPodAutoscaling):
        #  Cluster-level Vertical Pod Autoscaling
        #  configuration.
        cluster = container_v1.Cluster(
            name=self.name,
            description=self.description,
            autoscaling=cluster_autoscaling,
        )

        # We can either provide our own node pools, or a node count and initial size
        # Keep in mind this doesn't allow setting a min or max!
        if node_pools is not None:
            cluster.node_pools = node_pools
        else:
            node_config = self.get_node_config(
                self.machine_type, spot=self.spot, labels=self.labels
            )
            cluster.initial_node_count = self.node_count
            cluster.node_config = node_config

        print("\n🥣️ cluster spec")
        print(cluster)
        return cluster

    @timed
    def update_cluster(self, size, max_nodes, min_nodes):
        """
        Update a cluster. Currently we support the max and min size
        """
        autoscaling = container_v1.NodePoolAutoscaling(
            enabled=True,
            total_max_node_count=max_nodes,
            total_min_node_count=min_nodes,
        )
        request = container_v1.SetNodePoolAutoscalingRequest(
            autoscaling=autoscaling,
            name=f"projects/{self.project}/locations/{self.location}/clusters/{self.name}/nodePools/{self.default_pool}",
        )
        print("\n🥣️ cluster node pool update request")
        print(request)

        response = self.client.set_node_pool_autoscaling(request=request)
        print(response)

        # Status 2 is running (1 is provisioning)
        print(f"⏱️   Waiting for {self.cluster_name} to be ready...")
        return self.wait_for_status(2)

    @timed
    def create_cluster(self):
        """
        Create a cluster, with hard coded variables for now.

        Since we can't create an empty cluster, and the API doesn't allow you
        to create one from scratch setting a min/max count, what we are going
        to do is create the NodePool (with our preferences) first, and then
        give it to the new cluster.
        """
        node_config = self.get_node_config(
            self.machine_type, spot=self.spot, labels=self.labels
        )

        # If you don't set this, your cluster will grow as it pleases.
        autoscaling = container_v1.NodePoolAutoscaling(
            enabled=True,
            total_max_node_count=self.max_nodes,
            total_min_node_count=self.min_nodes,
        )
        node_pool = container_v1.types.NodePool(
            name=self.default_pool,
            config=node_config,
            initial_node_count=self.node_count,
            autoscaling=autoscaling,
            # not specifying network_config uses cluster defaults
            # Note that we can define placement_policy
            # (google.cloud.container_v1.types.NodePool.PlacementPolicy)
        )

        # Get a cluster with the given node pool
        cluster = self.get_cluster([node_pool])

        # https://github.com/googleapis/google-cloud-python/blob/461c76bbc6bd7cda3ef6da0a0ec7e2418c1532aa/packages/google-cloud-container/google/cloud/container_v1/services/cluster_manager/client.py#L708
        request = container_v1.CreateClusterRequest(
            parent=f"projects/{self.project}/locations/{self.location}",
            cluster=cluster,
        )
        print("\n🥣️ cluster creation request")
        print(request)

        # Make the request
        response = self.client.create_cluster(request=request)
        print(response)

        # Status 2 is running (1 is provisioning)
        print(f"⏱️   Waiting for {self.cluster_name} to be ready...")
        return self.wait_for_status(2)

    @property
    def cluster_name(self):
        return f"projects/{self.project}/locations/{self.location}/clusters/{self.name}"

    def wait_for_delete(self):
        """
        Wait until the cluster is running (status 2 I think?)
        """
        sleep = self.sleep_time
        while True:
            time.sleep(sleep)

            # https://github.com/googleapis/python-container/blob/main/google/cloud/container_v1/types/cluster_service.py#L3569
            request = container_v1.GetClusterRequest(name=self.cluster_name)
            # Make the request
            try:
                self.client.get_cluster(request=request)
            except NotFound:
                return

            # Some other issue
            except Exception:
                raise
            sleep = sleep * self.sleep_multiplier

    def wait_for_status(self, status=2):
        """
        Wait until the cluster is running (status 2 I think?)

        status codes:
        provisioning: 1
        running: 2
        reconciling: 3
        stopping: 4
        """
        sleep = self.sleep_time

        # https://github.com/googleapis/python-container/blob/main/google/cloud/container_v1/types/cluster_service.py#L3569
        request = container_v1.GetClusterRequest(name=self.cluster_name)
        response = None

        while not response or response.status.value != status:
            if response:
                print(
                    f"Cluster {self.cluster_name} does not have status {status}, found {response.status}. Sleeping {sleep}"
                )
            time.sleep(sleep)

            # Make the request
            response = self.client.get_cluster(request=request)
            sleep = sleep * self.sleep_multiplier

        # Get it once more before returning (has complete size, etc)
        return self.client.get_cluster(request=request)
