# Copyright 2023 Lawrence Livermore National Security, LLC and other
# HPCIC DevTools Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (MIT)

__version__ = "0.0.14"
AUTHOR = "Vanessa Sochat"
EMAIL = "vsoch@users.noreply.github.com"
NAME = "kubescaler"
PACKAGE_URL = "https://github.com/converged-computing/kubescaler"
KEYWORDS = "Kubernetes, elasticity, scaling, EKS, GKE"
DESCRIPTION = "Helper classes for scaling Kubernetes clusters"
LICENSE = "LICENSE"

################################################################################
# Global requirements

# Since we assume wanting Singularity and lmod, we require spython and Jinja2

INSTALL_REQUIRES = (
    ("ruamel.yaml", {"min_version": None}),
    ("jsonschema", {"min_version": None}),
    ("kubernetes", {"min_version": None}),
)

AWS_REQUIRES = (
    ("awscli", {"min_version": None}),
    ("boto3", {"min_version": None}),
)

# Prefer discovery clients - more control
GOOGLE_CLOUD_REQUIRES = (
    ("google-cloud-container", {"min_version": None}),
    ("google-api-python-client", {"min_version": None}),
)

TESTS_REQUIRES = (("pytest", {"min_version": "4.6.2"}),)

################################################################################
# Submodule Requirements (versions that include database)

INSTALL_REQUIRES_ALL = (
    INSTALL_REQUIRES + GOOGLE_CLOUD_REQUIRES + AWS_REQUIRES + TESTS_REQUIRES
)
