import base64
import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("install-credentials.py")
SPEC = importlib.util.spec_from_file_location("install_credentials", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InstallCredentialsTests(unittest.TestCase):
    def test_installs_login_without_exposing_other_registry_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "docker-config.json"
            encoded = base64.b64encode(b"strawgatepydantic:public-read-test-token").decode()
            source.write_text(
                json.dumps(
                    {
                        "auths": {
                            "https://index.docker.io/v1/": {"auth": encoded},
                            "ghcr.io": {"auth": "must-not-copy"},
                        }
                    }
                )
            )
            destination = root / "mirror" / "credentials.env"

            MODULE.install(source, destination)

            self.assertEqual(stat.S_IMODE(destination.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            self.assertEqual(
                destination.read_text(),
                "REGISTRY_PROXY_USERNAME=strawgatepydantic\n"
                "REGISTRY_PROXY_PASSWORD=public-read-test-token\n",
            )

    def test_rejects_the_wrong_docker_hub_account(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "docker-config.json"
            encoded = base64.b64encode(b"someone-else:token").decode()
            source.write_text(json.dumps({"auths": {"https://index.docker.io/v1/": {"auth": encoded}}}))
            destination = root / "mirror" / "credentials.env"

            with self.assertRaisesRegex(ValueError, "strawgatepydantic"):
                MODULE.install(source, destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
