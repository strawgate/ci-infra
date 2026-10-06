import copy
import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
RENDERER = ROOT / "node/helm-plugins/arc-kata/render.py"


def render(doc):
    result = subprocess.check_output([str(RENDERER)], input=yaml.safe_dump(doc), text=True)
    return yaml.safe_load(result)


class RendererTests(unittest.TestCase):
    def fixture(self, dind=True):
        pod = {
            "runtimeClassName": "kata-clh-runtime-rs",
            "resources": {"requests": {"cpu": "4", "memory": "8Gi"},
                          "limits": {"cpu": "4", "memory": "8Gi"}},
            "containers": [{"name": "runner", "image": "private:qualified",
                            "resources": {"limits": {"cpu": "4"}}}],
            "volumes": [{"name": "work", "emptyDir": {}},
                        {"name": "pnpm-store", "hostPath": {"path": "/shared"}}],
        }
        if dind:
            pod["initContainers"] = [{"name": "dind", "args": ["dockerd"],
                                     "volumeMounts": [], "restartPolicy": "Always"}]
        return {"kind": "AutoscalingRunnerSet", "spec": {"template": {"spec": pod}}}

    def test_dind_storage_and_cache_ownership_are_idempotent(self):
        result = render(self.fixture())
        self.assertEqual(render(result), result)
        pod = result["spec"]["template"]["spec"]
        self.assertNotIn("resources", pod["containers"][0])
        ownership = pod["initContainers"][0]
        self.assertEqual(ownership["command"], ["chown", "1001:1001", "/mnt/work", "/mnt/docker-store"])
        self.assertEqual(ownership["securityContext"]["capabilities"]["add"], ["CHOWN"])
        dind = pod["initContainers"][1]
        self.assertEqual(dind["startupProbe"]["timeoutSeconds"], 10)
        self.assertIn("@sha256:", dind["image"])
        self.assertIn("--registry-mirror=http://192.168.122.1:5000", dind["args"])
        self.assertEqual(pod["resources"]["limits"]["cpu"], "4")

    def test_non_dind_runner_stays_non_dind(self):
        doc = self.fixture(False)
        result = render(doc)
        pod = result["spec"]["template"]["spec"]
        self.assertNotIn("initContainers", pod)
        self.assertEqual(pod["volumes"], doc["spec"]["template"]["spec"]["volumes"])
        self.assertEqual(pod["containers"][0]["image"], "private:qualified")

    def test_unrelated_resources_and_old_runtime_are_untouched(self):
        self.assertEqual(render({"kind": "ConfigMap", "data": {"x": "y"}}),
                         {"kind": "ConfigMap", "data": {"x": "y"}})
        doc = self.fixture()
        original = copy.deepcopy(doc)
        original["spec"]["template"]["spec"]["runtimeClassName"] = "runc"
        self.assertEqual(render(original), original)
