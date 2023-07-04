# Copyright 2023 Lawrence Livermore National Security, LLC and other
# HPCIC DevTools Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (MIT)

import base64
import json
import os
import sys
import tempfile
import time

try:
    import boto3
except ImportError:
    sys.exit("Please pip install kubescaler[aws]")

from kubernetes import client as k8s
from kubernetes import utils as k8sutils

import kubescaler.utils as utils
from kubescaler.cluster import Cluster
from kubescaler.decorators import retry, timed
from kubescaler.logger import logger

from .ami import get_latest_ami
from .template import auth_config_data, vpc_template, workers_template
from .token import get_bearer_token

stack_failure_options = ["DELETE", "DO_NOTHING", "ROLLBACK"]


class EKSCluster(Cluster):
    """
    A scaler for an Amazon EKS Cluster
    """

    default_region = "us-east-1"

    def __init__(
        self,
        name,
        admin_role_name=None,
        kube_config_file=None,
        keypair_name=None,
        keypair_file=None,
        on_stack_failure="DELETE",
        stack_timeout_minutes=15,
        auth_config_file=None,
        **kwargs,
    ):
        """
        Create an Amazon Cluster
        """
        super().__init__(name=name, **kwargs)

        # name for K8s IAM role
        self.admin_role_name = admin_role_name or "EKSServiceAdmin"

        # Secrets files
        self.keypair_name = keypair_name or "workers-pem"
        self.keypair_file = keypair_file or "aws-worker-secret.pem"
        self.auth_config_file = auth_config_file or "aws-auth-config.yaml"

        # You might want to update this to better debug (so not deleted)
        # DO_NOTHING | ROLLBACK | DELETE
        self.set_stack_failure(on_stack_failure)
        self.stack_timeout_minutes = max(1, stack_timeout_minutes)
        self.token_expires = kwargs.get("token_expires")

        # Here we define cluster name from name
        self.cluster_name = self.name
        self.tags = self.tags or {}
        if not isinstance(self.tags, dict):
            raise ValueError("Tags must be key value pairs (dict)")

        # kube config file (this is no longer used)
        self.kube_config_file = kube_config_file or "kubeconfig-aws.yaml"
        self.image_ami = get_latest_ami(self.region, self.kubernetes_version)
        self.machine_type = self.machine_type or "m5.large"
        self.configuration = None
        self._kubectl = None

        # Client connections
        self.session = boto3.Session(region_name=self.region)
        self.ec2 = self.session.client("ec2")
        self.cf = self.session.client("cloudformation")
        self.iam = self.session.client("iam")
        self.eks = self.session.client("eks")

        # Will be set later!
        self.workers_stack = None
        self.vpc_stack = None
        self.vpc_security_group = None
        self.vpc_subnet_private = None
        self.vpc_subnet_public = None
        self.vpc_id = None
        self.set_roles()

    def set_stack_failure(self, on_stack_failure):
        """
        Set the action to take if a stack fails to create.
        """
        self.on_stack_failure = on_stack_failure
        if self.on_stack_failure not in stack_failure_options:
            options = " | ".join(stack_failure_options)
            raise ValueError(
                f"{on_stack_failure} is not a valid option, choices are: {options}"
            )

    @timed
    def create_cluster(self):
        """
        Create a cluster.

        To verify this is working, you should be able to view the Cloud Formation
        in the console to see the VPC stack, and when that is complete, go to
        EKS to see the cluster being created. When the cluster is created and
        the nodes are up, the wait_for_nodes function should finish a little
        bit after. If you don't see this happening, usually it means a mismatch
        between the credentials you used to create the cluster, and the ones
        that the AWS client discovers here (in token.py) to generate a token.
        It's best to be consistent and use an environment set (that ideally
        has a long enough expiration) OR just the $HOME/.aws/config.
        """
        print("🥞️ Creating VPC stack and subnets...")
        self.set_vpc_stack()
        self.set_subnets()

        # Save cluster metadata so we can get the k8s client later
        try:
            self.cluster = self.eks.describe_cluster(name=self.cluster_name)
        except Exception:
            print("🥣️ Creating cluster...")
            self.cluster = self.new_cluster()

        # Get the status and confirm it's active
        status = self.cluster["cluster"]["status"]
        if status != "ACTIVE":
            raise ValueError(
                f"Found cluster {self.cluster_name} but status is {status} and should be ACTIVE"
            )

        # Get cluster endpoint and security info so we can make kubectl config
        self.certificate = self.cluster["cluster"]["certificateAuthority"]["data"]
        self.endpoint = self.cluster["cluster"]["endpoint"]

        # Ensure we have a config to interact with, and write the keypair file
        self.ensure_kube_config()
        self.get_keypair()

        # The cluster is actually created with no nodes - just the control plane!
        # Here is where we create the workers, via a stack. Because apparently
        # AWS really likes their pancakes. 🥞️
        self.set_workers_stack()
        self.create_auth_config()

        # We can only wait for the node group after we set the auth config!
        # I was surprised this is expecting the workers name and not the node
        # group name.
        self.wait_for_nodes()

        print(f"🦊️ Writing config file to {self.kube_config_file}")
        print(f"  Usage: kubectl --kubeconfig={self.kube_config_file} get nodes")
        return self.cluster

    def get_k8s_client(self):
        """
        Get a client to use to interact with the cluster, either corev1.api
        or the kubernetes api client.

        https://github.com/googleapis/python-container/issues/6
        """
        if self._kubectl:
            return self._kubectl

        # Save the configuration for advanced users to user later
        if not self.configuration:
            # This is separate in case we need to manually call it (expires, etc.)
            self._generate_configuration()

        # This has .api_client for just the api client
        self._kubectl = k8s.CoreV1Api(k8s.ApiClient(self.configuration))
        return self._kubectl

    def _generate_configuration(self):
        """
        Generate the kubectl configuration, no matter what.

        This is separate from the get_k8s_client function as we might want
        to call it to regenerate the self.configuration and self._kubectl.
        """
        # Get a token from the aws client, which must be installed
        # aws eks get-token --cluster-name example
        token = get_bearer_token(self.cluster_name, self.token_expires)
        configuration = k8s.Configuration()
        configuration.host = self.cluster["cluster"]["endpoint"]
        with tempfile.NamedTemporaryFile(delete=False) as ca_cert:
            ca_cert.write(
                base64.b64decode(
                    self.cluster["cluster"]["certificateAuthority"]["data"]
                )
            )
            configuration.ssl_ca_cert = ca_cert.name
        configuration.api_key_prefix["authorization"] = "Bearer"
        configuration.api_key["authorization"] = token["status"]["token"]
        self.configuration = configuration

    @timed
    def wait_for_nodes(self):
        """
        Wait for the nodes to be ready.

        We do this separately to allow timing. This function would be improved if
        we didn't need subprocess, but the waiter doesn't seem to work.
        """
        kubectl = self.get_k8s_client()
        while True:
            print(f"⏱️ Waiting for {self.node_count} nodes to be Ready...")
            time.sleep(5)
            nodes = kubectl.list_node()
            ready_count = 0
            for node in nodes.items:
                for condition in node.status.conditions:
                    # Don't add to node ready count if not ready
                    if condition.type == "Ready" and condition.status == "True":
                        ready_count += 1
            if ready_count == self.node_count:
                break

        # The waiter doesn't seem to work - so we call kubectl until it's ready
        # waiter = self.eks.get_waiter("nodegroup_active")
        # waiter.wait(clusterName=self.cluster_name, nodegroupName=self.node_autoscaling_group_name)

    def create_auth_config(self):
        """
        Deploy a config map that tells the master how to contact the workers

        After this, kubectl --kubeconfig=./kubeconfig.yaml get nodes
        will (or I should say "should") work!
        """
        # Easier to write to file and then apply!
        auth_config = auth_config_data % self.node_instance_role
        utils.write_file(auth_config, self.auth_config_file)
        kubectl = self.get_k8s_client()

        try:
            k8sutils.create_from_yaml(kubectl.api_client, self.auth_config_file)
        except Exception as e:
            print(f"😭️ Kubectl create from yaml returns in error: {e}")

    def ensure_kube_config(self):
        """
        Ensure the kubernetes kubectl config file exists

        Since this might change, let's always just write it again.
        We require the user to install awscli so the aws executable
        should be available.
        """
        cluster_config = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [
                {
                    "cluster": {
                        "server": str(self.endpoint),
                        "certificate-authority-data": str(self.certificate),
                    },
                    "name": "kubernetes",
                }
            ],
            "contexts": [
                {"context": {"cluster": "kubernetes", "user": "aws"}, "name": "aws"}
            ],
            "current-context": "aws",
            "preferences": {},
            "users": [
                {
                    "name": "aws",
                    "user": {
                        "exec": {
                            "apiVersion": "client.authentication.k8s.io/v1beta1",
                            "command": "aws",
                            "args": [
                                "--region",
                                self.region,
                                "eks",
                                "get-token",
                                "--cluster-name",
                                self.cluster_name,
                            ],
                        }
                    },
                }
            ],
        }
        utils.write_yaml(cluster_config, self.kube_config_file)

    def get_keypair(self):
        """
        Write keypair file.
        """
        try:
            # Check if keypair exists, if not, ignore this step.
            return self.ec2.describe_key_pairs(KeyNames=[self.keypair_name])
        except Exception:
            return self.create_keypair()

    def create_keypair(self):
        """
        Create the keypair secret and associated file.
        """
        key = self.ec2.create_key_pair(KeyName=self.keypair_name)
        private_key = key["KeyMaterial"]

        # Write to file - this needs to be managed by client runner
        # to ensure uniqueness of names (and not rewriting existing files)
        utils.write_file(private_key, self.keypair_file)
        os.chmod(self.keypair_file, 400)
        return key

    def set_workers_stack(self):
        """
        Get or create the workers stack, or the nodes for the cluster.
        """
        try:
            self.workers_stack = self.cf.describe_stacks(StackName=self.workers_name)
        except Exception:
            self.workers_stack = self.create_workers_stack()

        # We need this role to later associate master with workers
        self.node_instance_role = None
        for output in self.workers_stack["Stacks"][0]["Outputs"]:
            if output["OutputKey"] == "NodeInstanceRole":
                self.node_instance_role = output["OutputValue"]
            if output["OutputKey"] == "NodeAutoScalingGroup":
                self.node_autoscaling_group_name = output["OutputValue"]

    @timed
    def delete_workers_stack(self):
        """
        Delete the workers stack.
        """
        return self.delete_stack(self.workers_name)

    @timed
    def delete_vpc_stack(self):
        """
        Delete the vpc stack
        """
        return self.delete_stack(self.vpc_name)

    @timed
    def create_workers_stack(self):
        """
        Create the workers stack (the nodes for the EKS cluster)
        """
        stack = self.cf.create_stack(
            StackName=self.workers_name,
            TemplateURL=workers_template,
            Capabilities=["CAPABILITY_IAM"],
            Parameters=[
                {"ParameterKey": "ClusterName", "ParameterValue": self.cluster_name},
                {
                    "ParameterKey": "ClusterControlPlaneSecurityGroup",
                    "ParameterValue": self.vpc_security_group,
                },
                {
                    "ParameterKey": "NodeGroupName",
                    "ParameterValue": self.node_group_name,
                },
                {
                    "ParameterKey": "NodeAutoScalingGroupMinSize",
                    "ParameterValue": str(self.min_nodes),
                },
                {
                    "ParameterKey": "NodeAutoScalingGroupDesiredCapacity",
                    "ParameterValue": str(self.node_count),
                },
                {
                    "ParameterKey": "NodeAutoScalingGroupMaxSize",
                    "ParameterValue": str(self.max_nodes),
                },
                {
                    "ParameterKey": "NodeInstanceType",
                    "ParameterValue": self.machine_type,
                },
                {"ParameterKey": "NodeImageId", "ParameterValue": self.image_ami},
                {"ParameterKey": "KeyName", "ParameterValue": self.keypair_name},
                {"ParameterKey": "VpcId", "ParameterValue": self.vpc_id},
                {
                    "ParameterKey": "Subnets",
                    "ParameterValue": ",".join(self.vpc_subnet_ids),
                },
            ],
            TimeoutInMinutes=self.stack_timeout_minutes,
            OnFailure=self.on_stack_failure,
        )
        return self._create_stack(stack, self.workers_name)

    def new_cluster(self):
        """
        Create a new cluster.
        """
        # Create Kubernetes cluster.
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/eks/client/create_cluster.html
        self.eks.create_cluster(
            name=self.cluster_name,
            version=str(self.kubernetes_version),
            roleArn=self.role_arn,
            tags=self.tags,
            resourcesVpcConfig={
                "subnetIds": self.vpc_subnet_ids,
                "securityGroupIds": [self.vpc_security_group],
            },
        )
        logger.info("⭐️ Cluster creation started! Waiting...")
        waiter = self.eks.get_waiter("cluster_active")
        waiter.wait(name=self.cluster_name)

        # When it's ready, save the cluster
        return self.eks.describe_cluster(name=self.cluster_name)

    def set_vpc_stack(self):
        """
        Get the stack
        """
        # Does it already exist?
        try:
            self.vpc_stack = self.cf.describe_stacks(StackName=self.vpc_name)
        except Exception:
            self.vpc_stack = self.create_vpc_stack()

    @timed
    def create_vpc_stack(self):
        """
        Create a new stack from the template
        """
        # If not, create it from the template
        stack = self.cf.create_stack(
            StackName=self.vpc_name,
            TemplateURL=vpc_template,
            Parameters=[],
            TimeoutInMinutes=self.stack_timeout_minutes,
            OnFailure=self.on_stack_failure,
        )
        return self._create_stack(stack, self.vpc_name)

    def _create_stack(self, stack, stack_name):
        """
        Shared function to check validity of stack and wait!

        I didn't add retry here, because it usually fails for some
        "good" reason (e.g., not enough network)
        """
        if stack is None:
            raise ValueError("Could not create stack")

        if "StackId" not in stack:
            raise ValueError("Could not create VPC stack")

        try:
            logger.info(f"Waiting for {stack_name} stack...")
            waiter = self.cf.get_waiter("stack_create_complete")
            # MaxAttempts defaults to 120, and Delay 30 seconds
            waiter.wait(StackName=stack_name)
        except Exception as e:
            # Allow waiting 3 more minutes
            print(f"Waiting for stack creation exceeded wait time: {e}")
            time.sleep(180)

        # Retrieve the same metadata if we had retrieved it
        return self.cf.describe_stacks(StackName=stack_name)

    def delete_stack(self, stack_name):
        """
        Delete a stack and wait for it to be deleted
        """
        logger.info(f"🥞️ Attempting delete of stack {stack_name}...")
        try:
            self.cf.delete_stack(StackName=stack_name)
        except Exception:
            logger.warning(f"Stack {stack_name} does not exist.")
            return
        try:
            logger.info(f"Waiting for {stack_name} to be deleted..")
            waiter = self.cf.get_waiter("stack_delete_complete")
            waiter.wait(StackName=stack_name)
        except Exception:
            raise ValueError("Waiting for stack deletion exceeded wait time.")

    def set_roles(self):
        """
        Create the default IAM arn role for the admin
        """
        try:
            # See if role exists.
            self.role = self.iam.get_role(RoleName=self.admin_role_name)
        except Exception:
            self.role = self.create_role()
        self.role_arn = self.role["Role"]["Arn"]

    def create_role(self):
        """
        Create the role for eks
        """
        # This is an AWS role policy document.  Allows access for EKS.
        policy_doc = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Action": "sts:AssumeRole",
                        "Effect": "Allow",
                        "Principal": {"Service": "eks.amazonaws.com"},
                    }
                ],
            }
        )

        # Create role and attach needed policies for EKS
        role = self.iam.create_role(
            RoleName=self.admin_role_name,
            AssumeRolePolicyDocument=policy_doc,
            Description="Role providing access to EKS resources from EKS",
        )

        self.iam.attach_role_policy(
            RoleName=self.admin_role_name,
            PolicyArn="arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
        )

        self.iam.attach_role_policy(
            RoleName=self.admin_role_name,
            PolicyArn="arn:aws:iam::aws:policy/AmazonEKSServicePolicy",
        )
        return role

    def set_subnets(self):
        """
        Create VPC subnets
        """
        if not self.vpc_stack:
            raise ValueError("set_subnets needs to be called after stack creation.")

        # Unwrap list of outputs into values we care about.
        for output in self.vpc_stack["Stacks"][0]["Outputs"]:
            if output["OutputKey"] == "SecurityGroups":
                self.vpc_security_group = output["OutputValue"]
            if output["OutputKey"] == "VPC":
                self.vpc_id = output["OutputValue"]
            if output["OutputKey"] == "SubnetsPublic":
                self.vpc_subnet_public = output["OutputValue"].split(",")
            if output["OutputKey"] == "SubnetsPrivate":
                self.vpc_subnet_private = output["OutputValue"].split(",")

    @property
    def vpc_subnet_ids(self):
        """
        Get listing of private and public subnet ids
        """
        vpc_subnet_ids = []
        if self.vpc_subnet_private is not None:
            vpc_subnet_ids += self.vpc_subnet_private
        if self.vpc_subnet_public is not None:
            vpc_subnet_ids += self.vpc_subnet_public
        return vpc_subnet_ids

    @property
    def vpc_name(self):
        return self.name + "-vpc"

    @property
    def workers_name(self):
        return self.name + "-workers"

    @property
    def node_group_name(self):
        return self.cluster_name + "-worker-group"

    @timed
    def delete_cluster(self):
        """
        Delete the cluster

        Let's be conservative and leave the kube config files, because if
        something goes wrong we want to be able to interact with them.
        And let's go backwards - deleting first what we created last.
        """
        logger.info("🔨️ Deleting node workers...")
        self.delete_workers_stack()
        # We could delete keypair, but let's keep for now, assuming could be reused elsewhere
        # and a deletion might be unexpected to the user

        # Now delete the cluster
        try:
            self.eks.delete_cluster(name=self.cluster_name)
        except Exception as e:
            logger.info(f"⏳️ Cluster likely already deleted: {e}")
            return

        logger.info("⏳️ Cluster deletion started! Waiting...")
        waiter = self.eks.get_waiter("cluster_deleted")
        waiter.wait(name=self.cluster_name)

        # Delete the VPC stack and we are done!
        logger.info("🥅️ Deleting VPC and associated assets...")
        self.delete_vpc_stack()
        self.delete_workers_stack()
        logger.info("⭐️ Done!")

    @property
    def data(self):
        """
        Combine class data into json object to save
        """
        return {
            "times": self.times,
            "cluster_name": self.cluster_name,
            "machine_type": self.machine_type,
            "name": self.name,
            "region": self.region,
            "tags": self.tags,
            "description": self.description,
        }

    @retry
    def scale(self, count):
        """
        Make a request to scale the cluster
        """
        response = self.cf.update_stack(
            StackName=self.workers_name,
            UsePreviousTemplate=True,
            Capabilities=["CAPABILITY_IAM"],
            Parameters=[
                {
                    "ParameterKey": "NodeAutoScalingGroupDesiredCapacity",
                    "ParameterValue": str(count),
                },
                {"ParameterKey": "ClusterName", "UsePreviousValue": True},
                {
                    "ParameterKey": "ClusterControlPlaneSecurityGroup",
                    "ParameterValue": self.vpc_security_group,
                },
                {
                    "ParameterKey": "NodeGroupName",
                    "ParameterValue": self.node_group_name,
                },
                {
                    "ParameterKey": "NodeAutoScalingGroupMinSize",
                    "ParameterValue": str(self.min_nodes),
                },
                {
                    "ParameterKey": "NodeAutoScalingGroupDesiredCapacity",
                    "ParameterValue": str(count),
                },
                {
                    "ParameterKey": "NodeAutoScalingGroupMaxSize",
                    "ParameterValue": str(self.max_nodes),
                },
                {"ParameterKey": "KeyName", "ParameterValue": self.keypair_name},
                {"ParameterKey": "VpcId", "ParameterValue": self.vpc_id},
                {
                    "ParameterKey": "Subnets",
                    "ParameterValue": ",".join(self.vpc_subnet_ids),
                },
            ],
        )

        # Wait for stack update to be complete. Note this does not seem
        # to work. Instead we update the node count and then wait for the nodes.
        # waiter = self.cf.get_waiter('stack_update_complete')
        # waiter.wait(StackName=self.workers_name)

        # If successful, save new node count
        self.node_count = count
        self.wait_for_nodes()
        return response
