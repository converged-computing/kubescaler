# Copyright 2023 Lawrence Livermore National Security, LLC and other
# HPCIC DevTools Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (MIT)


from datetime import datetime, timedelta

from awscli.customizations.eks.get_token import (
    TOKEN_EXPIRATION_MINS,
    STSClientFactory,
    TokenGenerator,
)
from botocore import session


def get_expiration_time(expires_minutes=TOKEN_EXPIRATION_MINS):
    token_expires = datetime.utcnow() + timedelta(minutes=expires_minutes)
    return token_expires.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_bearer_token(
    cluster_name: str, token_expire_minutes: int = None, role_arn: str = None
) -> dict:
    """
    Create an STS session to generate a token for EKS
    """
    token_expire_minutes = token_expire_minutes or TOKEN_EXPIRATION_MINS
    work_session = session.get_session()
    client_factory = STSClientFactory(work_session)
    sts_client = client_factory.get_sts_client(role_arn=role_arn)
    token = TokenGenerator(sts_client).get_token(cluster_name)
    return {
        "kind": "ExecCredential",
        "apiVersion": "client.authentication.k8s.io/v1alpha1",
        "spec": {},
        "status": {
            "expirationTimestamp": get_expiration_time(token_expire_minutes),
            "token": token,
        },
    }
