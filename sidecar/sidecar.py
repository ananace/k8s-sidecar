from kubernetes import client, config, watch
import datetime
import glob
import os
import requests
import shutil
import sys
import tempfile
from requests.packages.urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter


def time():
  return datetime.datetime.now().strftime("[%Y-%m-%d %H:%M]")


def str2bool(v):
  return v.lower() in ("yes", "true", "y", "t", "1")


def writeTextToFile(folder, filename, data, header = None):
    with open(folder +"/"+ filename, 'w') as f:
        if header is not None:
            f.write(header)
            f.write("\n")
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
    res = None

    if url is None:
        return
    # If method is not provided use GET as default
    elif method == "GET" or method is None:
        res = r.get("%s" % url, timeout=10)
    elif method == "POST":
        res = r.post("%s" % url, json=payload, timeout=10)

    print("%s %s request sent to %s. Response: %d %s" % (time(), method, url, res.status_code, res.reason))


def removeFile(folder, filename):
    completeFile = folder +"/"+filename
    if os.path.isfile(completeFile):
        os.remove(completeFile)
    else:
        print("Error: %s file not found" % completeFile)


def applyChanges(targetFolder, eventType, dataMap, metadata,
                 realTargetFolder = None, concatFile = None,
                 concatHeader = None, hashMap = None):
    update = False

    if concatFile:
        curTargetFolder = targetFolder+'/'+metadata.namespace+'/'+metadata.name
        if not os.path.exists(curTargetFolder):
            os.makedirs(curTargetFolder)
    else:
        curTargetFolder = targetFolder

    for filename in dataMap.keys():
        if concatFile and concatHeader is not None:
            sourcedefinition = '%s/%s:%s' % (
                metadata.namespace,
                metadata.name,
                filename
            )
            curConcatHeader = concatHeader+' '+sourcedefinition
        else:
            curConcatHeader = None

        hashKey = metadata.namespace + '/' + metadata.name + ':' + filename
        print('- %s' % filename)
        if (eventType == "ADDED") or (eventType == "MODIFIED"):
            if hashMap is not None:
                dataHash = hash(dataMap[filename])
                if hashMap.get(hashKey) == dataHash:
                    print('(Data unchanged, ignoring)')
                    continue
                hashMap[hashKey] = dataHash
            writeTextToFile(curTargetFolder, filename, dataMap[filename],
                            header=curConcatHeader)
        else:
            removeFile(curTargetFolder, filename)
            if hashMap is not None and hashKey in hashMap:
                del hashMap[hashKey]
        update = True

    if update and concatFile:
        with open(realTargetFolder+'/'+concatFile, 'w') as outfile:
            for sourcefile in glob.iglob(targetFolder+'/**', recursive=True):
                if not os.path.isfile(sourcefile):
                    continue
                with open(sourcefile, 'r') as infile:
                    shutil.copyfileobj(infile, outfile)
                outfile.write("\n")

    return update


def runWatch(func, label, targetFolder, realTargetFolder, url, method, payload,
             concatFile, concatHeader, considerateUpdate, hashMap,
             **kwargs):
    w = watch.Watch()

    if 'resource_version' in kwargs and kwargs['resource_version'] > 0:
        print(f'{time()} Resuming watch for configmaps with resource version %s.' %
              kwargs['resource_version'])
    else:
        if 'resource_version' in kwargs:
            del kwargs['resource_version']

        print(f'{time()} Starting watch for configmaps.')

    for event in w.stream(func, **kwargs):
        metadata = event['object'].metadata
        if metadata.labels is None:
            continue

        update = False
        if label in event['object'].metadata.labels.keys():
            eventType = event['type']

            print(f'{time()} {eventType} configmap {metadata.namespace}/{metadata.name}')
            dataMap=event['object'].data
            if dataMap is None:
                print('(Configmap does not have data, ignoring)')
                continue

            if applyChanges(targetFolder, eventType, dataMap,
                            metadata=event['object'].metadata,
                            realTargetFolder=realTargetFolder,
                            concatFile=concatFile,
                            concatHeader=concatHeader,
                            hashMap=hashMap):
                update = True

        if update and url is not None:
            request(url, method, payload)

    return w.resource_version


def watchForChanges(label, targetFolder, url, method, payload, namespace,
                    concatFile, concatHeader, considerateUpdate, timeout):
    v1 = client.CoreV1Api()

    hashMap = None
    if considerateUpdate:
        hashMap = dict()

    stream = None
    realTargetFolder = targetFolder
    if concatFile:
        targetFolder = tempfile.mkdtemp()

    func = None
    kwargs = dict()
    if namespace == "ALL":
        func = v1.list_config_map_for_all_namespaces
    else:
        func = v1.list_namespaced_config_map
        kwargs['namespace'] = namespace

    if timeout is not None:
      kwargs['timeout_seconds'] = timeout

    while True:
      version = runWatch(
        func, label, targetFolder, realTargetFolder, url, method, payload,
        concatFile, concatHeader, considerateUpdate, hashMap, **kwargs
      )
      if version is not None:
        kwargs['resource_version'] = int(version)

      if timeout is None:
        break

def main():
    print("Starting config map collector")
    label = os.getenv('LABEL')
    if label is None:
        print("ERROR: Missing LABEL as environment variable!")
        return -1
    targetFolder = os.getenv('FOLDER')
    if targetFolder is None:
        print("ERROR: Missing FOLDER as environment variable!")
        return -1

    namespace = os.getenv('NAMESPACE', open("/var/run/secrets/kubernetes.io/serviceaccount/namespace").read())
    print("Using namespace %s." % namespace)

    concatFile = os.getenv('CONCAT')
    if concatFile is not None:
        print("Concat given, combining all changes into a single file.")

    concatHeader = os.getenv('CONCAT_HEADER')
    if concatHeader is not None and concatFile is None:
        print("Concat header specified but not concatenating files?")

    considerateUpdate = str2bool(os.getenv('CONSIDERATE_UPDATE', '1'))
    if considerateUpdate:
        print("Using considerate update.")

    timeout = os.getenv('TIMEOUT')
    if timeout is not None:
        timeout = int(timeout)
        print("Using timeout of %d seconds." % timeout)

    method = os.getenv('REQ_METHOD')
    url = os.getenv('REQ_URL')
    payload = os.getenv('REQ_PAYLOAD')

    config.load_incluster_config()
    print("Config for cluster api loaded.\n")
    watchForChanges(label, targetFolder, url, method, payload, namespace,
                    concatFile, concatHeader, considerateUpdate, timeout)


if __name__ == '__main__':
    main()
