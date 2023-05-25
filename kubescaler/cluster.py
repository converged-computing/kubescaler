# Copyright 2023 Lawrence Livermore National Security, LLC and other
# HPCIC DevTools Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (MIT)

import os

import kubescaler.defaults as defaults
from kubescaler.utils import write_json


class Cluster:
    """
    A base cluster controller for scaling.
    """

    def __init__(
        self,
        name=None,
        description=None,
        tags=None,
        region=None,
        node_count=2,
        sleep_seconds=3,
        sleep_multiplier=1,
        max_nodes=3,
        min_nodes=0,
        machine_type=None,
        kubernetes_version=None,
    ):
        """
        A simple class to control creating a cluster
        """
        self.node_count = node_count

        # List or dict depending on cloud
        self.tags = tags
        self.name = os.path.basename(name or "kubescaler-cluster")
        self.max_nodes = max_nodes
        self.min_nodes = max(0, min_nodes)
        self.description = description or "A Kubescaler testing cluster"
        self.sleep_seconds = sleep_seconds
        self.kubernetes_version = kubernetes_version or defaults.kubernetes_version
        self.machine_type = machine_type

        # Sleep time multiplication factor must be > 1, defaults to 1.5
        self.sleep_multiplier = max(sleep_multiplier or 1, 1)
        self.sleep_time = sleep_seconds or 2

        # Region or default region
        self.region = region or self.default_region

        # Easy way to save times
        self.times = {}

    def delete_cluster(self):
        """
        Delete the cluster
        """
        raise NotImplementedError

    def save(self, results_file):
        """
        Save results to file.
        """
        write_json(self.data, results_file)

    @property
    def data(self):
        """
        Combine class data into json object to save
        """
        raise NotImplementedError

    def scale(self, *args, **kwargs):
        """
        Make a request to scale the cluster
        """
        raise NotImplementedError

    def resize_cluster(self, *args, **kwargs):
        """
        Do the resize of the cluster
        """
        raise NotImplementedError

    def create_cluster(self):
        """
        Create a cluster, with hard coded variables for now.
        """
        raise NotImplementedError
