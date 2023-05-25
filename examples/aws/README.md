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
