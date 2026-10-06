import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeployTests(unittest.TestCase):
    def run_deploy(self, version, fail_apply=False):
        with tempfile.TemporaryDirectory() as directory:
            directory = pathlib.Path(directory)
            calls = directory / "calls"
            scripts = {
                "kubectl": """#!/bin/sh
printf 'kubectl %s\\n' "$*" >> "$ARC_TEST_CALLS"
if [ "$1" = get ]; then printf kata-clh-runtime-rs; fi
if [ "$1" = apply ] && [ "$ARC_TEST_FAIL_APPLY" = 1 ]; then exit 42; fi
""",
                "helm": """#!/bin/sh
printf 'helm %s\\n' "$*" >> "$ARC_TEST_CALLS"
if [ "$1" = version ]; then printf '%s' "$ARC_TEST_HELM_VERSION"; fi
""",
            }
            for name, content in scripts.items():
                path = directory / name
                path.write_text(content)
                path.chmod(0o755)
            environment = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ["PATH"],
                               ARC_TEST_CALLS=str(calls), ARC_TEST_HELM_VERSION=version,
                               ARC_TEST_FAIL_APPLY="1" if fail_apply else "0")
            result = subprocess.run(["bash", str(ROOT / "kata/deploy-runners.sh")],
                                    env=environment, text=True, capture_output=True)
            return result, calls.read_text().splitlines()

    def test_configmap_precedes_all_eight_upgrades_on_both_helm_versions(self):
        for version in ["v3.19.5", "v4.2.0"]:
            with self.subTest(version=version):
                result, calls = self.run_deploy(version)
                self.assertEqual(result.returncode, 0, result.stderr)
                upgrades = [c for c in calls if c.startswith("helm upgrade")]
                self.assertEqual(len(upgrades), 8)
                config = next(c for c in calls if c.startswith("kubectl apply"))
                self.assertIn("node/docker-daemon-configmap.yaml", config)
                self.assertLess(calls.index(config), calls.index(upgrades[0]))
                renderer = ("arc-kata" if version.startswith("v4")
                            else str(ROOT / "node/helm-plugins/arc-kata/render.py"))
                self.assertTrue(all("--post-renderer " + renderer in c for c in upgrades))
                self.assertTrue(all("--version 0.14.2" in c for c in upgrades))

    def test_configmap_failure_stops_the_rollout(self):
        result, calls = self.run_deploy("v3.19.5", fail_apply=True)
        self.assertEqual(result.returncode, 42)
        self.assertFalse(any(c.startswith("helm upgrade") for c in calls))
