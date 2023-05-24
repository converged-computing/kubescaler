from google.cloud import container_v1
from google.api_core.exceptions import NotFound
from kubescaler.decorators import timed, retry
from kubescaler.cluster import Cluster
import time

class GKECluster(Cluster):
    """
    A scaler for a Google Kubernetes Engine (GKE) cluster
    """
    def __init__(
        self,
        project,
        *args,
        machine_type="c2-standard-8",
        machine_type_memory_gb=32,
        machine_type_vcpu=8,
        region="us-central1-a",
        **kwargs
    ):
        """
        A simple class to control creating a cluster
        """
        super().__init__(*args, **kwargs)

        # This client we can use to interact with Google Cloud GKE
        # https://github.com/googleapis/python-container/blob/main/google/cloud/container_v1/services/cluster_manager/client.py#L96
        print("⭐️ Creating global cluster manager client...")
        self.client = container_v1.ClusterManagerClient()
        self.project = project
        self.region = region
        self.machine_type = machine_type
        self.machine_type_vcpu = machine_type_vcpu
        self.machine_type_memory_gb = machine_type_memory_gb

    @timed
    def delete_cluster(self):
        """
        Delete the cluster
        """
        request = container_v1.DeleteClusterRequest(name=self.cluster_name)
        # Make the request, and check until deleted!
        self.client.delete_cluster(request=request)
        self.wait_for_delete()
        # TODO we need a wait for create too!

    @property
    def zone(self):
        """
        The region is the zone minus the last letter!
        """
        return self.region.rsplit("-", 1)[0]

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
            "tags": self.tags,
            "description": self.description,
        }

    def scale_up(self, count, pool_name="default-pool"):
        """
        Make a request to scale the cluster
        """
        return self.scale(count, count, count + 1, pool_name=pool_name)

    def scale_down(self, count, pool_name="default-pool"):
        """
        Make a request to scale the cluster
        """
        return self.scale(count, max(count - 1, 0), count, pool_name=pool_name)

    def scale(self, count, min_count, max_count, pool_name="default-pool"):
        """
        Make a request to scale the cluster
        """
        node_pool_name = f"{self.cluster_name}/nodePools/{pool_name}"

        # Always make the max node count one more than we want
        # I'm not sure if we need to change the policy with the size
        autoscaling = container_v1.NodePoolAutoscaling(
            enabled=True,
            min_node_count=min_count,
            max_node_count=max_count,
            #            total_min_node_count=count,
            #            total_max_node_count=count,
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

    @property
    def node_config(self):
        """
        Create the node config

        Note that instead of initial_node_count + node_config above,
        we could just use node_pool. I think the first creates the second,
        and I'm not sure about pros/cons.
        """
        # Note that if you use GKE Autopilot you need to use a different class, see the link:
        # https://github.com/googleapis/python-container/blob/main/google/cloud/container_v1/types/cluster_service.py#L448
        node_config = container_v1.NodeConfig(
            machine_type=self.machine_type,
            tags=self.tags
            # metadata = {"startup-script": my_startup_script,
            #            "user-data": my_user_data}
        )
        print("\n🥣️ cluster node_config")
        print(node_config)
        return node_config

    @property
    def cluster(self):
        """
        Get the cluster proto with our defaults
        """
        # Design our initial cluster!
        # https://github.com/googleapis/python-container/blob/main/google/cloud/container_v1/types/cluster_service.py#LL2119C1-L2124C1

        # Command for comparison
        # TODO I don't see where dataplane is, or cloud dns, can add later!
        # gcloud container clusters create flux-cluster \
        #   --region=us-central1-a --project $GOOGLE_PROJECT \
        #   --machine-type c2d-standard-112 --num-nodes=32 \
        #   --cluster-dns=clouddns --cluster-dns-scope=cluster \
        #   --tags=flux-cluster  --enable-dataplane-v2 \
        #   --threads-per-core=1
        # Note: we can add node_config for customizing node pools further

        # TODO these look useful / interesting
        # autoscaling (google.cloud.container_v1.types.ClusterAutoscaling):
        #  Cluster-level autoscaling configuration.

        # Autoscaling - try optimizing
        # PROFILE_UNSPECIFIED = 0
        # OPTIMIZE_UTILIZATION = 1
        # BALANCED = 2
        autoscaling_profile = container_v1.ClusterAutoscaling.AutoscalingProfile(1)

        # These are hard coded for c2-standard-8
        # https://cloud.google.com/compute/docs/compute-optimized-machines
        resource_limits = [
            container_v1.ResourceLimit(
                resource_type="cpu",
                minimum=self.machine_type_vcpu,
                maximum=self.machine_type_vcpu * self.max_nodes,
            ),
            container_v1.ResourceLimit(
                resource_type="memory",
                minimum=self.machine_type_memory_gb,
                maximum=self.machine_type_memory_gb * self.max_nodes,
            ),
        ]
        cluster_autoscaling = container_v1.ClusterAutoscaling(
            enable_node_autoprovisioning=True,
            autoprovisioning_locations=[self.zone],
            autoscaling_profile=autoscaling_profile,
            resource_limits=resource_limits,
        )

        # vertical_pod_autoscaling (google.cloud.container_v1.types.VerticalPodAutoscaling):
        #  Cluster-level Vertical Pod Autoscaling
        #  configuration.
        cluster = container_v1.Cluster(
            name=self.name,
            description=self.description,
            initial_node_count=self.node_count,
            node_config=self.node_config,
            autoscaling=cluster_autoscaling,
        )
        print("\n🥣️ cluster spec")
        print(cluster)
        return cluster

    @timed
    def create_cluster(self):
        """
        Create a cluster, with hard coded variables for now.
        """
        # https://github.com/googleapis/python-container/blob/main/google/cloud/container_v1/types/cluster_service.py#L3527
        request = container_v1.CreateClusterRequest(
            parent=f"projects/{self.project}/locations/{self.region}",
            cluster=self.cluster,
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
        return f"projects/{self.project}/locations/{self.region}/clusters/{self.name}"

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
