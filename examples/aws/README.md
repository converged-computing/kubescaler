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
