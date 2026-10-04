"""Validate the rendered, pinned charts, not just the input values."""
import pathlib
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
    worker = yaml.safe_load((ROOT / "worker-config.yaml").read_text())
    assert worker["node-name"] == "docker-host-kata"
    assert worker["node-ip"] == "192.168.122.1"
    assert worker["node-taint"] == ["ci-infra/kata-only=true:NoSchedule"]
    assert "reserved-cpus=0-3,8-39,44-71" in worker["kubelet-arg"]
    assert "system-reserved=cpu=64,memory=288Gi" in worker["kubelet-arg"]
    docs = render("oci://ghcr.io/kata-containers/kata-deploy-charts/kata-deploy",
                  "4.2.0", "kata-values.yaml")
    classes = [doc for doc in docs if doc["kind"] == "RuntimeClass"]
    assert len(classes) == 1, "Only Cloud Hypervisor may be installed"
    runtime = classes[0]
    assert runtime["metadata"]["name"] == "kata-clh-runtime-rs"
    assert runtime["scheduling"]["nodeSelector"]["ci-infra/kata-worker"] == "true"
    assert runtime["overhead"]["podFixed"] == {"cpu": "250m", "memory": "768Mi"}

    docs = render("oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set",
                  "0.14.2", "runner-values.yaml", "--post-renderer", "arc-dind-mirror")
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
    assert dind["securityContext"]["privileged"]
    assert pod["tolerations"] == [{
        "key": "ci-infra/kata-only", "operator": "Equal",
        "value": "true", "effect": "NoSchedule",
    }]
    for volume in pod["volumes"]:
        if "hostPath" in volume:
            assert volume["hostPath"]["path"] == "/data/gha-o11yfleet/arc-kata/pnpm-store"
    if "--smoke-pod" in sys.argv:
        # Exact chart-generated runner/DinD topology without registering a runner.
        runner = next(c for c in pod["containers"] if c["name"] == "runner")
        runner["command"] = ["sleep", "1800"]
        yaml.safe_dump({"apiVersion": "v1", "kind": "Pod", "metadata": {
            "name": "kata-runner-smoke", "namespace": "arc-runners"}, "spec": pod}, sys.stdout)
    else:
        print("Pinned Kata/ARC charts render with isolated scheduling and bounded resources")


if __name__ == "__main__":
    main()
