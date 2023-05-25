# Copyright 2023 Lawrence Livermore National Security, LLC and other
# HPCIC DevTools Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (MIT)

import json
import os
import sys

try:
    import boto3
except ImportError:
    sys.exit("Please pip install kubescaler[aws]")

from kubernetes import client as k8s
from kubernetes import config
from kubernetes import utils as k8sutils

import kubescaler.utils as utils
from kubescaler.cluster import Cluster
from kubescaler.decorators import timed
from kubescaler.logger import logger

from .ami import get_latest_ami
from .template import auth_config_data, vpc_template, workers_template

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
        super().__init__(**kwargs)

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

        # Here we define cluster name from name
        self.cluster_name = name
        self.tags = self.tags or {}
        if not isinstance(self.tags, dict):
            raise ValueError("Tags must be key value pairs (dict)")

        # kube config file
        self.kube_config_file = kube_config_file or "kubeconfig-aws.yaml"
        self.image_ami = get_latest_ami(self.region, self.kubernetes_version)
        self.machine_type = self.machine_type or "m5.large"

        # Client connections
        self.session = boto3.Session(region_name=self.region)
        self.ec2 = self.session.client("ec2")
        self.cf = self.session.client("cloudformation")
        self.iam = self.session.client("iam")
        self.eks = self.session.client("eks")

        # Will be set later!
        self.workers_stack = None
        self.workers_stack_id = None

        self.vpc_stack = None
        self.vpc_stack_id = None
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
        Create a cluster
        """
        self.set_vpc_stack()
        self.set_subnets()

        try:
            cluster = self.eks.describe_cluster(name=self.cluster_name)
        except Exception:
            cluster = self.new_cluster()

        # Get the status and confirm it's active
        status = cluster["cluster"]["status"]
        if status != "ACTIVE":
            raise ValueError(
                f"Found cluster {self.cluster_name} but status is {status} and should be ACTIVE"
            )

        # Get cluster endpoint and security info so we can make kubectl config
        self.certificate = cluster["cluster"]["certificateAuthority"]["data"]
        self.endpoint = cluster["cluster"]["endpoint"]

        # Ensure we have a config to interact with, and write the keypair file
        self.ensure_kube_config()
        self.get_keypair()

        # The cluster is actually created with no nodes - just the control plane!
        # Here is where we create the workers, via a stack. Because apparently
        # AWS really likes their pancakes.
        self.set_workers_stack()
        self.create_auth_config()

        print(f"Writing config file to {self.kube_config_file}")
        print(f"  Usage: kubectl --kubeconfig={self.kube_config_file} get nodes")

    def create_auth_config(self):
        """
        Deploy a config map that tells the master how to contact the workers

        After this, kubectl --kubeconfig=./kubeconfig.yaml get nodes
        will (or I should say "should") work!
        """
        # Easier to write to file and then apply!
        auth_config = auth_config_data % self.node_instance_role
        utils.write_file(auth_config, self.auth_config_file)

        # We can likely do it this way in the future (will open issue)
        config.load_kube_config(self.kube_config_file)
        koobcli = k8s.ApiClient()
        return k8sutils.create_from_yaml(koobcli, self.auth_config_file)

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
        self.workers_stack_id = self.workers_stack["StackId"]

        # We need this role to later associate master with workers
        self.node_instance_role = None
        for output in self.workers_stack["Stacks"][0]["Outputs"]:
            if output["OutputKey"] == "NodeInstanceRole":
                self.node_instance_role = output["OutputValue"]

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
                    "ParameterValue": self.cluster_name + "-worker-group",
                },
                {
                    "ParameterKey": "NodeAutoScalingGroupMinSize",
                    "ParameterValue": str(self.min_nodes),
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
        self.vpc_stack_id = self.vpc_stack["StackId"]

    def create_stack(self):
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
        """
        if stack is None:
            raise ValueError("Could not create stack")

        if "StackId" not in stack:
            raise ValueError("Could not create VPC stack")

        try:
            logger.info(f"Waiting for {stack_name} stack...")
            waiter = self.cf.get_waiter("stack_create_complete")
            waiter.wait(StackName=stack_name)
        except Exception:
            raise ValueError("Waiting for stack exceeded wait time.")

        # Retrieve the same metadata if we had retrieved it
        return self.cf.describe_stacks(StackName=stack_name)

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
        if not self.stack:
            raise ValueError("set_subnets needs to be called after stack creation.")

        # Unwrap list of outputs into values we care about.
        for output in self.stack["Stacks"][0]["Outputs"]:
            if output["OutputKey"] == "SecurityGroups":
                self.vpc_security_group = output["OutputValue"]
            if output["OutputKey"] == "VPC":
                self.vpc_id = output["OutputValue"]
            if output["OutputKey"] == "SubnetsPublic":
                self.vpc_subnet_public = output["OutputValue"].split(",")
            if output["OutputKey"] == "SubnetsPrivate":
                self.vpc_subnet_private = output["OutputValue"].split(",")

    @property
    def vpc_submit_ids(self):
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

    @timed
    def delete_cluster(self):
        """
        Delete the cluster
        """
        print("TODO DELETE")
        import IPython

        IPython.embed()

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
