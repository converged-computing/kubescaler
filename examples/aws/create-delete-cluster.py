#!/usr/bin/env python3

import argparse
import sys
import time

from kubescaler.scaler import EKSCluster


def get_parser():
    parser = argparse.ArgumentParser(
        description="K8s Cluster Creator / Destroyer!",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "cluster_name", nargs="?", help="Cluster name suffix", default="flux-cluster"
    )
    parser.add_argument(
        "--experiment", help="Experiment name (defaults to script name)", default=None
    )
    parser.add_argument("--node-count", help="starting node count", type=int, default=2)
    parser.add_argument(
        "--max-node-count", help="maximum node count", type=int, default=3
    )
    parser.add_argument(
        "--min-node-count",
        help="minimum node count",
        type=int,
        default=1,
    )
    parser.add_argument("--machine-type", help="AWS machine type", default="m5.large")
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
    cluster_name = f"{experiment_name}-{cluster_name}"
    print(f"📛️ Cluster name is {cluster_name}")

    print(
        f"⭐️ Creating the cluster sized {args.min_node_count} to {args.max_node_count}..."
    )
    cli = EKSCluster(
        name=cluster_name,
        node_count=args.node_count,
        max_nodes=args.max_node_count,
        min_nodes=args.min_node_count,
    )
    cli.create_cluster()
    print("⭐️ Deleting the cluster...")
    cli.delete_cluster()


if __name__ == "__main__":
    main()
