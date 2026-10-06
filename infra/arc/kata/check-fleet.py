"""Validate every rendered fleet template before deploying any scale set."""
import sys

import yaml

sets = [d for d in yaml.safe_load_all(sys.stdin)
        if d and d.get("kind") == "AutoscalingRunnerSet"]
assert len(sets) == 1
spec = sets[0]["spec"]
pod = spec["template"]["spec"]
assert pod["runtimeClassName"] == "kata-clh-runtime-rs"
assert pod["nodeSelector"] == {"ci-infra/kata-worker": "true"}
assert {"key": "ci-infra/kata-only", "operator": "Equal",
        "value": "true", "effect": "NoSchedule"} in pod["tolerations"]
assert pod["resources"]["requests"] == pod["resources"]["limits"]
runner = next(c for c in pod["containers"] if c["name"] == "runner")
assert "resources" not in runner, "All sandbox containers must share the pod budget"
assert all("subPath" not in m for m in runner.get("volumeMounts", []))
assert any(s["name"] == "ghcr" for s in pod["imagePullSecrets"])
for volume in pod.get("volumes", []):
    if "hostPath" in volume:
        assert volume["hostPath"]["path"] == "/data/gha-o11yfleet/arc-kata/pnpm-store"
dind = next((c for c in pod.get("initContainers", []) if c["name"] == "dind"), None)
if dind:
    assert dind["restartPolicy"] == "Always"
    assert dind["startupProbe"]["timeoutSeconds"] >= 10
    assert "@sha256:" in dind["image"]
    assert "--registry-mirror=http://192.168.122.1:5000" in dind["args"]
    assert "--mtu=1450" in dind["args"]
    assert "--default-network-opt=bridge=com.docker.network.driver.mtu=1450" in dind["args"]
    assert next(e for e in runner["env"] if e["name"] == "DOCKER_HOST")["value"] == "unix:///var/run/docker.sock"
    assert next(v for v in pod["volumes"] if v["name"] == "docker-store")["emptyDir"]["sizeLimit"] == "32Gi"
    ownership = pod["initContainers"][0]
    assert ownership["name"] == "kata-volume-ownership"
    emptydirs = {v["name"] for v in pod["volumes"] if "emptyDir" in v}
    assert {v["name"] for v in ownership["volumeMounts"]} == emptydirs
print(spec["runnerScaleSetName"] + ": Kata scheduling, storage and limits verified")
