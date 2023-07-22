# AWS Examples

## Create and Delete a Cluster

This example shows creating and deleting a cluster. You should be able to run
this  also if a cluster is already created. First, make sure your AWS credentials
are exported:

```bash
export AWS_ACCESS_KEY_ID=xxxxxxxxxxxxxxxx
export AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxx
export AWS_SESSION_TOKEN=xxxxxxxxxxxxxxxxxxxxxx
```

And then run the script (using defaults, min size 1, max size 3)

```bash
$ python create-delete-cluster.py --min-node-count 1 --max-node-count 3 --machine-type m5.large
```

## Test Scale

Here are some example runs for testing the time it takes to scale a cluster up.
We also time separate components of scaling, like creating the worker pool and
the vpc. We do small max sizes here since it's just a demo! This first example runs on GKE:

```bash
$ pip install -e .[aws]
$ pip install -e kubescaler[aws]
```
```bash
# Test scale up in increments of 1 (up to 3) for c2-standard-8 (the default) just one iteration!
$ python test-scale.py --increment 1 small-cluster --max-node-count 3 --min-node-count 0 --start-iter 0 --end-iter 1

# Slightly more reasonable experiment
$ python test-scale.py --increment 1 test-cluster --max-node-count 32 --min-node-count 0 --start-iter 0 --end-iter 10

# Test scale down in increments of 2 (5 down to 1) for 10 iterations (default)
$ python test-scale.py --increment 2 test-cluster --down --max-node-count 5 --down
```

Arguments
```console
usage: test-scale.py [-h] [--outdir OUTDIR] [--experiment EXPERIMENT] [--start-iter START_ITER] [--end-iter ITERS] [--max-node-count MAX_NODE_COUNT] [--min-node-count MIN_NODE_COUNT] [--start-node-count START_NODE_COUNT] [--machine-type MACHINE_TYPE] [--eks-nodegroup] [--increment INCREMENT] [--down] [cluster_name]

K8s Scaling Experiment Runner

positional arguments:
  cluster_name          Cluster name suffix

optional arguments:
  -h, --help                show this help message and exit
  --outdir OUTDIR           output directory for results
  --experiment EXPERIMENT   Experiment name (defaults to script name)
  --start-iter START_ITER   start at this iteration
  --end-iter ITERS          end at this iteration
  --max-node-count MAX_NODE_COUNT   maximum node count
  --min-node-count MIN_NODE_COUNT   minimum node count
  --start-node-count START_NODE_COUNT   start at this many nodes and go up
  --machine-type MACHINE_TYPE   AWS machine type
  --increment INCREMENT     Increment by this value
  --down                    Test scaling down
  --eks-nodegroup           Include this to use eks managed nodegroup, otherwise, it'll use cloudformation stack
```



Several timings that this program tracks. 

| Metric              | Description |
| :---------------- | :------ |
| create_vpc_stack        |   Amount of time it takes to create a cloudformation vpc stack   |
| new_cluster           |   Amount of time it takes to deploy a cluster using boto3 eks `create_cluster`   |
| create_workers_stack    |  Amount of time it takes to create a eks nodegroup or cloudformation worker stacks (depending on the input you provided when creating the cluster)   |
| wait_for_nodes |  If you specified initial number of nodes, then this will track how long it takes for kubernetes to get those nodes   |
| create_cluster | Total aggregrated time for creating a cluster, this includes all the above metrics |
| watch_for_nodes_in_aws | When we perform scaling up, we track three timings in parallel. This metrics track how longs it takes to show a node in the aws when we do scale up operation in the code |
| wait_for_stack_updates | We perform scale up by updating the cloudformation stack or eks nodegroup, which update the desired size in the autoscaling group, so this updates takes time. we track this to know how long it takes for the cloudformation or eks nodegroup to complete its update |
| wait_for_nodes_in_k8s | this metrics tracks how long it takes for the nodes to show up in kubernetes once we apply the scale up operation | 
| delete_workers_stack | This one tracks the time to delete a cloudformation stack or eks nodegroup |
| _delete_cluster | this one's shows how much time it takes when we call `boto3.eks.delete_cluster()` |
| delete_vpc | time to delete a cloudformation stack for vpc |
| delete_cluster | Total time to tear down a cluster including the above deletion times |
