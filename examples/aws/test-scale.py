#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time

from kubescaler.scaler.aws import EKSCluster
from kubescaler.utils import read_json

# Save data here
here = os.path.dirname(os.path.abspath(__file__))

# Create data output directory
data = os.path.join(here, "data")


def get_parser():
    parser = argparse.ArgumentParser(
        description="K8s Scaling Experiment Runner",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "cluster_name", nargs="?", help="Cluster name suffix", default="flux-cluster"
    )
    parser.add_argument(
        "--outdir",
        help="output directory for results",
        default=data,
    )
    parser.add_argument(
        "--experiment", help="Experiment name (defaults to script name)", default=None
    )
    parser.add_argument(
        "--start-iter", help="start at this iteration", type=int, default=0
    )
    parser.add_argument(
        "--end-iter", help="end at this iteration", type=int, default=3, dest="iters"
    )
    parser.add_argument(
        "--max-node-count", help="maximum node count", type=int, default=3
    )
    parser.add_argument(
        "--min-node-count", help="minimum node count", type=int, default=0
    )
    parser.add_argument(
        "--start-node-count",
        help="start at this many nodes and go up",
        type=int,
        default=1,
    )
    parser.add_argument("--machine-type", help="AWS machine type", default="m5.large")
    parser.add_argument(
        "--increment", help="Increment by this value", type=int, default=1
    )
    parser.add_argument(
        "--down", action="store_true", help="Test scaling down", default=False
    )
    return parser


def main():
    """
    This experiment will test scaling a cluster, three times, each
    time going from 2 nodes to 32. We want to understand if scaling is
    impacted by cluster size.
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

    # Shared tags for logging and output
    if args.down:
        direction = "decrease"
        tag = "down"
    else:
        direction = "increase"
        tag = "up"

    # Update cluster name to include tag and increment
    experiment_name = f"{experiment_name}-{tag}-{args.increment}"
    print(f"📛️ Experiment name is {experiment_name}")

    # Prepare an output directory, named by cluster
    outdir = os.path.join(args.outdir, experiment_name, cluster_name)
    if not os.path.exists(outdir):
        print(f"📁️ Creating output directory {outdir}")
        os.makedirs(outdir)

    # Define stopping conditions for two directions
    def less_than_max(node_count):
        return node_count <= args.max_node_count

    def greater_than_zero(node_count):
        return node_count > 0

    # Update cluster name to include experiment name
    cluster_name = f"{experiment_name}-{cluster_name}"
    print(f"📛️ Cluster name is {cluster_name}")

    # Create 10 clusters, each going up to 32 nodes
    for iter in range(args.start_iter, args.iters):
        results_file = os.path.join(outdir, f"scaling-{iter}.json")

        # Start at the max if we are going down, otherwise the starting count
        node_count = args.max_node_count if args.down else args.start_node_count
        print(
            f"⭐️ Creating the initial cluster, iteration {iter} with size {node_count}..."
        )
        cli = EKSCluster(
            name=cluster_name,
            node_count=node_count,
            machine_type=args.machine_type,
            min_nodes=args.min_node_count,
            max_nodes=args.max_node_count,
        )
        # Load a result if we have it
        if os.path.exists(results_file):
            result = read_json(results_file)
            cli.times = result["times"]

        # Create the cluster (this times it)
        res = cli.create_cluster()
        print(f"📦️ The cluster has {cli.node_count} nodes!")

        # Flip between functions to decide to keep going based on:
        # > 0 (we are decreasing from the max node count)
        # <= max nodes (we are going up from a min node count)
        keep_going = less_than_max
        if args.down:
            keep_going = greater_than_zero

        # Continue scaling until we reach stopping condition
        while keep_going(node_count):
            old_size = node_count

            # Are we doing down or up?
            if args.down:
                node_count -= args.increment
            else:
                node_count += args.increment

            # TODO Feature Request 
            # The issue is when node_count exceeds the max_node_counts, we can only know at the end of the iteration
            # However, by this time the scaling request is already going to the stack and the stack update fails. and the program wait for nodes indefinitely. 
            # Possible solution is to prevent this happening and also if stack update fails, we can do something. 
            # for now, Checking here to prevent node_count exceeding max nodes or min nodes.
            if not keep_going(node_count):
                break

            print(
                f"⚖️ Iteration {iter}: scaling to {direction} by {args.increment}, from {old_size} to {node_count}"
            )

            # Scale the cluster - we should do similar logic for the GKE client (one function)
            start = time.time()
            res = cli.scale(node_count)
            end = time.time()
            seconds = round(end - start, 3)
            cli.times[f"scale_{tag}_{old_size}_to_{node_count}"] = seconds
            
            # TODO Bug Fixed
            # Throwed error that res has no attribute named `initial_node_count`
            print(
                f"📦️ Scaling from {old_size} to {node_count} took {seconds} seconds, and the cluster now has {cli.node_count} nodes!"
            )

            # Save the times as we go
            print(json.dumps(cli.data, indent=4))
            cli.save(results_file)

        # Delete the cluster and clean up
        cli.delete_cluster()
        print(json.dumps(cli.data, indent=4))
        cli.save(results_file)


if __name__ == "__main__":
    main()
