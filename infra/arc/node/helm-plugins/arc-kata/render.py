#!/usr/bin/env python3
"""Configure guest-native ARC/Docker storage, keeping normal Docker transport."""
import sys

import yaml

docs = list(yaml.safe_load_all(sys.stdin))
for doc in docs:
    if not doc or doc.get("kind") != "AutoscalingRunnerSet":
        continue
    pod = doc["spec"]["template"]["spec"]
    if pod.get("runtimeClassName") != "kata-clh-runtime-rs":
        continue
    runner = next(c for c in pod["containers"] if c["name"] == "runner")
    # Allocate CPUs to the whole sandbox, not exclusively to the runner
    # container: dockerd and the VMM must share that same pod CPU set.
    runner.pop("resources", None)
    dind = next((c for c in pod.get("initContainers", []) if c["name"] == "dind"), None)
    if dind is None:
        continue
    # Newly formatted guest volumes otherwise belong only to root. The ARC
    # image's runner and externals-copy init container use uid/gid 1001.
    pod.setdefault("securityContext", {})["fsGroup"] = 1001
    # Executing the probe crosses a VM boundary; one second is too tight
    # during concurrent cold starts even when dockerd is healthy.
    probe = dind.setdefault("startupProbe", {})
    probe["timeoutSeconds"] = max(10, probe.get("timeoutSeconds", 1))
    for argument in ["--registry-mirror=http://192.168.122.1:5000",
                     "--insecure-registry=192.168.122.1:5000"]:
        if argument not in dind["args"]:
            dind["args"].append(argument)
    # Use the exact image qualified in the staged pilot, not the moving dind tag.
    dind["image"] = "docker.io/library/docker:dind@sha256:7dcdfc4a20246236f558175182ccace1eb15a41bd3eb119dd2284f393498b7c1"
    # Kata's block-plain emptyDir mode supplies a guest-native ext4 filesystem.
    # Docker's overlay snapshotter cannot use virtio-fs as its upper filesystem.
    if not any(v["name"] == "docker-store" for v in pod["volumes"]):
        pod["volumes"].append({"name": "docker-store", "emptyDir": {"sizeLimit": "32Gi"}})
    if not any(v["mountPath"] == "/var/lib/docker" for v in dind["volumeMounts"]):
        dind["volumeMounts"].append({"name": "docker-store", "mountPath": "/var/lib/docker"})
    # Fresh ext4 volume roots are owned by uid 0. Initialize only this pod's
    # emptyDir roots, not the shared host cache or any existing host directory.
    volumes = [v for v in pod["volumes"] if "emptyDir" in v]
    if not any(c["name"] == "kata-volume-ownership" for c in pod["initContainers"]):
        runner = next(c for c in pod["containers"] if c["name"] == "runner")
        pod["initContainers"].insert(0, {
            "name": "kata-volume-ownership", "image": runner["image"],
            "command": ["chown", "1001:1001", *["/mnt/" + v["name"] for v in volumes]],
            "securityContext": {"runAsUser": 0, "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"], "add": ["CHOWN"]}},
            "volumeMounts": [{"name": v["name"], "mountPath": "/mnt/" + v["name"]} for v in volumes],
        })
yaml.safe_dump_all(docs, sys.stdout, sort_keys=False)
