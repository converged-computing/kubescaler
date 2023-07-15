#!/usr/bin/env python3

import argparse
import sys
import time
import json
import kubescaler.utils as utils

from kubescaler.scaler.aws import EKSCluster


def get_parser():
    parser = argparse.ArgumentParser(
        description="K8s Cluster Creator / Destroyer!",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "cluster_name", nargs="?", help="Cluster name suffix", default="kubernetes-flux-operator"
    )
    parser.add_argument(
        "--experiment", help="Experiment name (defaults to script name)", default="hpa-ca-cluster"
    )
    parser.add_argument("--node-count", help="starting node count", type=int, default=1)
    parser.add_argument(
        "--max-node-count", help="maximum node count", type=int, default=5
    )
    parser.add_argument(
        "--min-node-count",
        help="minimum node count",
        type=int,
        default=1,
    )
    parser.add_argument("--machine-type", help="AWS machine type", default="m5.large")
    parser.add_argument("--operation", help="create or delete Cluster", default="create")
    return parser

def main():
    """
    Demonstrate creating and deleting a cluster. If the cluster exists,
    we should be able to retrieve it and not create a second one.
    """
    parser = get_parser()

    # If an error occurs while parsing the arguments, the interpreter will exit with value 2
    args, _ = parser.parse_known_args()

    # Pull cluster name out of argument
    cluster_name = args.cluster_name

    # Derive the experiment name, either named or from script
    experiment_name = args.experiment
    if not experiment_name:
        experiment_name = sys.argv[0].replace(".py", "")
    time.sleep(2)

    # Update cluster name to include experiment name
    cluster_name = f"{cluster_name}-{experiment_name}"
    print(f"📛️ Cluster name is {cluster_name}")

    cli = EKSCluster(
            name=cluster_name,
            node_count=args.node_count,
            max_nodes=args.max_node_count,
            min_nodes=args.min_node_count,
            machine_type=args.machine_type,
        )
    

    if args.operation == "create":

        print(
            f"⭐️ Creating the cluster sized {args.min_node_count} to {args.max_node_count}..."
        )
        
        cluster_details = cli.create_cluster()
        print(f"OIDC Provider - {cluster_details['cluster']['identity']['oidc']['issuer']}")
        # utils.write_file(cluster_details, 'cluster-details.json')
    else:
        print("⭐️ Deleting the cluster...")
        cli.delete_cluster()


if __name__ == "__main__":
    main()
