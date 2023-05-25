# Examples

These are quick examples for using the modules!

## Test Scale

Here are some example runs for testing the time it takes to scale a cluster up.
We do small max sizes here since it's just a demo! This first example runs on GKE:

```bash
$ pip install -e .[google]
$ pip install -e kubescaler[google]
```
```bash
# Test scale up in increments of 1 (up to 3) for c2-standard-8 (the default) just one iteration!
$ python test-scale.py --increment 1 test-cluster --max-node-count 3 --start-iter 0 --end-iter 1

# Test scale down in increments of 2 (5 down to 1) for 10 iterations (default)
$ python test-scale.py --increment 2 flux-cluster --down --max-node-count 5 --down
```
