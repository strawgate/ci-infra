"""Validate the rendered, pinned charts, not just the input values."""
import pathlib
import json
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent


def render(chart, version, values, *args):
    output = subprocess.check_output([
        "helm", "template", "kata-check", chart, "--version", version,
        "--namespace", "arc-runners", "--values", str(ROOT / values), *args,
    ], text=True)
    return [doc for doc in yaml.safe_load_all(output) if doc]


def main():
    settings = yaml.safe_load((ROOT / "kata-values.yaml").read_text())
    configmap = yaml.safe_load((ROOT / "../node/docker-daemon-configmap.yaml").read_text())
    daemon = json.loads(configmap["data"]["daemon.json"])
    assert daemon["mtu"] == 1450
    assert daemon["default-network-opts"]["bridge"]["com.docker.network.driver.mtu"] == "1450"
    assert settings["defaultShim"]["amd64"] == "clh-runtime-rs"
    assert 'emptydir_mode = "block-plain"' in settings["shims"]["clh-runtime-rs"]["dropIn"]
    assert 'sandbox_cgroup_only = true' in settings["shims"]["clh-runtime-rs"]["dropIn"]
    worker = yaml.safe_load((ROOT / "worker-config.yaml").read_text())
    assert worker["node-name"] == "docker-host-kata"
    assert worker["node-ip"] == "192.168.122.1"
    assert worker["node-taint"] == ["ci-infra/kata-only=true:NoSchedule"]
    assert "reserved-cpus=0-3,8-11,36-39,44-47" in worker["kubelet-arg"]
    assert "system-reserved=cpu=16,memory=122Gi" in worker["kubelet-arg"]
    assert "cgroup-driver=cgroupfs" in worker["kubelet-arg"]
    assert "topology-manager-scope=pod" in worker["kubelet-arg"]
    docs = render("oci://ghcr.io/kata-containers/kata-deploy-charts/kata-deploy",
                  "4.2.0", "kata-values.yaml")
    classes = [doc for doc in docs if doc["kind"] == "RuntimeClass"]
    assert len(classes) == 1, "Only Cloud Hypervisor may be installed"
    runtime = classes[0]
    assert runtime["metadata"]["name"] == "kata-clh-runtime-rs"
    assert runtime["scheduling"]["nodeSelector"]["ci-infra/kata-worker"] == "true"
    assert runtime["overhead"]["podFixed"] == {"cpu": "0", "memory": "768Mi"}

    docs = render("oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set",
                  "0.14.2", "runner-values.yaml", "--post-renderer", "arc-kata")
    sets = [doc for doc in docs if doc["kind"] == "AutoscalingRunnerSet"]
    assert len(sets) == 1
    spec = sets[0]["spec"]
    assert spec["maxRunners"] == 1 and spec["minRunners"] == 0
    pod = spec["template"]["spec"]
    assert pod["runtimeClassName"] == runtime["metadata"]["name"]
    assert pod["nodeSelector"] == {"ci-infra/kata-worker": "true"}
    assert pod["resources"]["limits"] == {"cpu": "4", "memory": "8Gi"}
    assert pod["resources"]["requests"] == pod["resources"]["limits"]
    dind = next(c for c in pod["initContainers"] if c["name"] == "dind")
    assert dind["restartPolicy"] == "Always"
    assert "--registry-mirror=http://192.168.122.1:5000" in dind["args"]
    assert "--mtu=1450" in dind["args"]
    assert "--default-network-opt=bridge=com.docker.network.driver.mtu=1450" in dind["args"]
    assert dind["securityContext"]["privileged"]
    assert pod["securityContext"]["fsGroup"] == 1001
    runner = next(c for c in pod["containers"] if c["name"] == "runner")
    assert next(e for e in runner["env"] if e["name"] == "DOCKER_HOST")["value"] == "unix:///var/run/docker.sock"
    assert next(v for v in pod["volumes"] if v["name"] == "docker-store")["emptyDir"]["sizeLimit"] == "32Gi"
    ownership = pod["initContainers"][0]
    assert ownership["name"] == "kata-volume-ownership"
    assert all(v["name"] != "pnpm-store" for v in ownership["volumeMounts"])
    assert pod["tolerations"] == [{
        "key": "ci-infra/kata-only", "operator": "Equal",
        "value": "true", "effect": "NoSchedule",
    }]
    for volume in pod["volumes"]:
        if "hostPath" in volume:
            assert volume["hostPath"]["path"] == "/data/gha-o11yfleet/arc-kata/pnpm-store"
    if "--agent-smoke-pod" in sys.argv:
        docs = render("oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set",
                      "0.14.2", "../values/agent-2c-8g.yaml", "--post-renderer", "arc-kata")
        spec = next(d["spec"] for d in docs if d["kind"] == "AutoscalingRunnerSet")
        pod = spec["template"]["spec"]
        runner = pod["containers"][0]
        runner["command"] = ["bash", "-c",
            "sudo dockerd --host=unix:///var/run/docker.sock --group=123 --storage-driver=vfs "
            ">/tmp/dockerd.log 2>&1 & exec sleep 1800"]
        pod["serviceAccountName"] = "default"
        pod["automountServiceAccountToken"] = False
        yaml.safe_dump({"apiVersion": "v1", "kind": "Pod", "metadata": {
            "name": "kata-agent-smoke", "namespace": "arc-runners"}, "spec": pod}, sys.stdout)
    elif "--smoke-pod" in sys.argv:
        # Exact chart-generated runner/DinD topology without registering a runner.
        runner = next(c for c in pod["containers"] if c["name"] == "runner")
        runner["command"] = ["sleep", "1800"]
        pod["serviceAccountName"] = "default"
        pod["automountServiceAccountToken"] = False
        yaml.safe_dump({"apiVersion": "v1", "kind": "Pod", "metadata": {
            "name": "kata-runner-smoke", "namespace": "arc-runners"}, "spec": pod}, sys.stdout)
    else:
        print("Pinned Kata/ARC charts render with isolated scheduling and bounded resources")


if __name__ == "__main__":
    main()
