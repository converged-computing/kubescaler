# Copyright 2023 Lawrence Livermore National Security, LLC and other
# HPCIC DevTools Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (MIT)

import boto3
from dateutil import parser

# aws ssm get-parameter --name /aws/service/eks/optimized-ami/1.26/amazon-linux-2/recommended/image_id --region us-east-1 --query "Parameter.Value" --output text


def get_latest_ami(region, kubernetes_version=1.26):
    """
    Get the latest AMI for a specific region.
    """
    client = boto3.client("ec2", region_name=region)
    filters = [({"Name": "name", "Values": [f"*-eks-node-{kubernetes_version}*"]})]
    image_listing = client.describe_images(Filters=filters)
    latest = filter_images(image_listing["Images"])
    return latest["ImageId"]


def filter_images(images):
    """
    Filter images down to latest
    """
    latest = None
    for image in images:
        if not latest:
            latest = image
            continue
        if parser.parse(image["CreationDate"]) > parser.parse(latest["CreationDate"]):
            latest = image
    return latest
