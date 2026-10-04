"""arc-runc and arc-runc.jq: the runtime wrapper that gives each DinD container the
runner pod's CPU quota. A wrong edit starts every job container with the node's 56
CPUs again, or not at all."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


@unittest.skipUnless(shutil.which("jq"), "needs jq")
class ArcRunc(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bundle = self.tmp / "bundle"
        self.bundle.mkdir()
        self.conf = self.tmp / "cpu.max"
        self.conf.write_text("200000 100000\n")
        # A stand-in for runc: records its arguments.
        self.calls = self.tmp / "calls"
        fake = self.tmp / "runc"
        fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{self.calls}"\n')
        fake.chmod(0o755)
        self.env = {**os.environ, "ARC_RUNC_RUNC": str(fake), "ARC_RUNC_CONF": str(self.conf),
                    "ARC_RUNC_FILTER": str(HERE / "arc-runc.jq")}

    def spec(self, spec: dict) -> None:
        (self.bundle / "config.json").write_text(json.dumps(spec))

    def run_wrapper(self, *args: str) -> dict:
        subprocess.run([str(HERE / "arc-runc"), *args], env=self.env, check=True)
        self.assertEqual(self.calls.read_text().splitlines(), [" ".join(args)])
        return json.loads((self.bundle / "config.json").read_text())

    def create(self) -> list[str]:
        # As containerd's runc shim calls it.
        return ["--root", "/var/run/docker/runtime-arc/moby", "--log", "log.json", "--log-format", "json",
                "create", "--bundle", str(self.bundle), "--pid-file", "init.pid", "abc123"]

    def test_a_container_without_a_quota_gets_the_pods(self) -> None:
        self.spec({"process": {"env": ["PATH=/bin"]}, "linux": {"resources": {"cpu": {"shares": 1024}}}})
        spec = self.run_wrapper(*self.create())
        self.assertEqual(spec["linux"]["resources"]["cpu"], {"shares": 1024, "quota": 200000, "period": 100000})
        self.assertEqual(spec["process"]["env"], ["PATH=/bin", "GOMAXPROCS=2", "PYTHON_CPU_COUNT=2"])

    def test_a_containers_own_quota_and_env_win(self) -> None:
        self.spec({"process": {"env": ["PYTHON_CPU_COUNT=7"]},
                   "linux": {"resources": {"cpu": {"quota": 50000, "period": 100000}}}})
        spec = self.run_wrapper(*self.create())
        self.assertEqual(spec["linux"]["resources"]["cpu"], {"quota": 50000, "period": 100000})
        # Half a CPU rounds up to one.
        self.assertEqual(spec["process"]["env"], ["PYTHON_CPU_COUNT=7", "GOMAXPROCS=1"])

    def test_bundle_equals_form(self) -> None:
        self.spec({"process": {}, "linux": {}})
        spec = self.run_wrapper("create", f"--bundle={self.bundle}", "abc123")
        self.assertEqual(spec["linux"]["resources"]["cpu"]["quota"], 200000)

    def test_other_commands_pass_through(self) -> None:
        self.spec({"process": {}, "linux": {}})
        for args in (["state", "abc123"], ["kill", "abc123", "9"], ["delete", "--force", "abc123"]):
            self.calls.unlink(missing_ok=True)
            self.assertEqual(self.run_wrapper(*args), {"process": {}, "linux": {}})

    def test_without_a_pod_quota_nothing_changes(self) -> None:
        self.conf.unlink()
        self.spec({"process": {}, "linux": {}})
        self.assertEqual(self.run_wrapper(*self.create()), {"process": {}, "linux": {}})

    def test_a_spec_jq_cannot_read_still_starts(self) -> None:
        (self.bundle / "config.json").write_text("not json")
        subprocess.run([str(HERE / "arc-runc"), *self.create()], env=self.env, check=True)
        self.assertEqual((self.bundle / "config.json").read_text(), "not json")
        self.assertFalse((self.bundle / "config.json.arc").exists())
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
