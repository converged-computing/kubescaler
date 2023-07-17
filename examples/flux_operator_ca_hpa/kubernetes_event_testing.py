from kubernetes import client as k8s
from kubernetes import utils as k8sutils
from kubernetes import watch, config
from datetime import datetime
import time
import json

config.load_kube_config(config_file="kubeconfig-aws.yaml")
k8s_client = k8s.CoreV1Api()
kubernetes_nodes = {}

def watch_for_new_nodes(count):
    watcher = watch.Watch()
    print(f"Event - address - status - reason - added to k8s")
    for event in watcher.stream(k8s_client.list_node):
        event_type = event['type']
        object = event['object']  # object is one of type return_type
        raw_object = event['raw_object']  # raw_object is a dict

        name = raw_object['metadata']['name']
        creation_timestamp = raw_object['metadata']['creationTimestamp']
        added_to_k8s = datetime.utcnow() - datetime.strptime(creation_timestamp, "%Y-%m-%dT%H:%M:%SZ")
        
        conditions = raw_object['status']['conditions']
        for condition in conditions:
            status = condition['status']
            reason = condition['reason']

            if condition['type'] == 'Ready' and condition['status'] == 'True':
                if name not in kubernetes_nodes.keys():
                    kubernetes_nodes[name] = {}
                
                kubernetes_nodes[name]['status'] = True
                # transition_time = datetime.strptime(condition['lastTransitionTime'], "%Y-%m-%dT%H:%M:%SZ")
                # if transition_time < update_started:
                #     time_elapsed += (update_started - transition_time).total_seconds()
                #     new_nodes += 1

        print(f"Event - {event_type}, {name}, {status}, {reason}, {added_to_k8s}")
        print(kubernetes_nodes)
        current_node_count = len(kubernetes_nodes.keys())
        
        if current_node_count == count:
            watcher.stop()
            # total_time = time_elapsed / new_nodes
            # print(f"Average Time for {count} Node to be ready - {total_time}")
            print(json.dumps(kubernetes_nodes))
        
        # if event_type == "ADDED":
        #     kubernetes_nodes[name] = {}
        #     creation_timestamp = raw_object['metadata']['creationTimestamp']
        #     kubernetes_nodes[name]["added_time"] = start_time - datetime.strptime(creation_timestamp, "%Y-%m-%dT%H:%M:%SZ")
        
        # elif event_type == "MODIFIED":
        #     conditions = raw_object['status']['conditions']
        #     for condition in conditions:
        #         if condition['type'] == 'Ready':
        #             status = condition['status']
        #             reason = condition['reason']

        # added_to_k8s = datetime.utcnow() - datetime.strptime(creation_timestamp, "%Y-%m-%dT%H:%M:%SZ")
        # print(f"Event - {event_type}, {name}, {status}, {reason}, {added_to_k8s}")
        

start = time.time()
watch_for_new_nodes(4)
print(f"Time for waiting for nodes - {time.time()-start}")