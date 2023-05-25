# Copyright 2023 Lawrence Livermore National Security, LLC and other
# HPCIC DevTools Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (MIT)

# Default templates retrieved from:
# https://docs.aws.amazon.com/eks/latest/userguide/creating-a-vpc.html
vpc_template = "https://s3.us-west-2.amazonaws.com/amazon-eks/cloudformation/2020-10-29/amazon-eks-ipv6-vpc-public-private-subnets.yaml"

# EKS node group (workers template)
# https://docs.aws.amazon.com/eks/latest/userguide/retrieve-ami-id.html
workers_template = "https://s3.us-west-2.amazonaws.com/amazon-eks/cloudformation/2022-12-23/amazon-eks-nodegroup.yaml"

# Other useful links for AMI
# https://docs.aws.amazon.com/eks/latest/userguide/retrieve-ami-id.html
# https://docs.aws.amazon.com/eks/latest/userguide/eks-optimized-amis.html
# aws ssm get-parameter --name /aws/service/eks/optimized-ami/1.26/amazon-linux-2/recommended/image_id --region us-east-1 --query "Parameter.Value" --output text

# Can't use jinja2 here, we actually need that double {{}}
auth_config_data = """apiVersion: v1
kind: ConfigMap
metadata:
  name: aws-auth
  namespace: kube-system
data:
  mapRoles: |
    - rolearn: %s
      username: system:node:{{EC2PrivateDNSName}}
      groups:
        - system:bootstrappers
        - system:nodes
"""
