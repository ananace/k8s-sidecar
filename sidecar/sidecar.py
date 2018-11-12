from kubernetes import client, config, watch
import glob
import os
import requests
import shutil
import sys
import tempfile
from requests.packages.urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter


def writeTextToFile(folder, filename, data):
    with open(folder +"/"+ filename, 'w') as f:
        f.write(data)
        f.write("\n")
        f.close()


def request(url, method, payload):
    r = requests.Session()
    retries = Retry(total = 5,
            connect = 5,
            backoff_factor = 0.2,
            status_forcelist = [ 500, 502, 503, 504 ])
    r.mount('http://', HTTPAdapter(max_retries=retries))
    r.mount('https://', HTTPAdapter(max_retries=retries))
    if url is None:
        print("No url provided. Doing nothing.")
        # If method is not provided use GET as default
    elif method == "GET" or method is None:
        res = r.get("%s" % url, timeout=10)
        print ("%s request sent to %s. Response: %d %s" % (method, url, res.status_code, res.reason))
    elif method == "POST":
        res = r.post("%s" % url, json=payload, timeout=10)
        print ("%s request sent to %s. Response: %d %s" % (method, url, res.status_code, res.reason))


def removeFile(folder, filename):
    completeFile = folder +"/"+filename
    if os.path.isfile(completeFile):
        os.remove(completeFile)
    else:
        print("Error: %s file not found" % completeFile)


def watchForChanges(label, targetFolder, url, method, payload, current,
                    concatFile, concatHeader):
    v1 = client.CoreV1Api()
    w = watch.Watch()
    stream = None
    namespace = os.getenv("NAMESPACE")
    if namespace is None:
        stream = w.stream(v1.list_namespaced_config_map, namespace=current)
    elif namespace == "ALL":
        stream = w.stream(v1.list_config_map_for_all_namespaces)
    else:
        stream = w.stream(v1.list_namespaced_config_map, namespace=namespace)

    if concatFile:
        realTargetFolder = targetFolder
        targetFolder = tempfile.mkdtemp()

    for event in stream:
        metadata = event['object'].metadata
        if metadata.labels is None:
            continue

        update = False
        print(f'Working on configmap {metadata.namespace}/{metadata.name}')
        if label in event['object'].metadata.labels.keys():
            print("Configmap with label found")
            dataMap=event['object'].data
            if dataMap is None:
                print("Configmap does not have data.")
                continue

            eventType = event['type']
            for filename in dataMap.keys():
                print("File in configmap %s %s" % (filename, eventType))
                if (eventType == "ADDED") or (eventType == "MODIFIED"):
                    writeTextToFile(targetFolder, filename, dataMap[filename])
                else:
                    removeFile(targetFolder, filename)
                update = True

            if concatFile:
                with open(realTargetFolder+'/'+concatFile, 'w') as outfile:
                    for sourcefile in glob.glob(targetFolder+'/*'):
                        if concatHeader is not None:
                            sourcedefinition = '%s/%s:%s' % (
                                event['object'].metadata.namespace,
                                event['object'].metadata.name,
                                os.path.basename(sourcefile)
                            )
                            outfile.write('\n'+concatHeader+' '+sourcedefinition+'\n')
                        with open(sourcefile, 'r') as infile:
                            shutil.copyfileobj(infile, outfile)

        if update and url is not None:
            request(url, method, payload)

def main():
    print("Starting config map collector")
    label = os.getenv('LABEL')
    if label is None:
        print("Missing LABEL as environment variable! Exit")
        return -1
    targetFolder = os.getenv('FOLDER')
    if targetFolder is None:
        print("Missing FOLDER as environment variable! Exit")
        return -1

    concatFile = os.getenv('CONCAT')
    if concatFile is not None:
        print("Concat given, combining all changes into a single file!")

    concatHeader = os.getenv('CONCAT_HEADER')
    if concatHeader is not None and concatFile is None:
        print("Concat header specified but not concatenating files, this is a noop")

    method = os.getenv('REQ_METHOD')
    url = os.getenv('REQ_URL')
    payload = os.getenv('REQ_PAYLOAD')

    config.load_incluster_config()
    print("Config for cluster api loaded...")
    namespace = open("/var/run/secrets/kubernetes.io/serviceaccount/namespace").read()
    watchForChanges(label, targetFolder, url, method, payload, namespace,
                    concatFile, concatHeader)


if __name__ == '__main__':
    main()
