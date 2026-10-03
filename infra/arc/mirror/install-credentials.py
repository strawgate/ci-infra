#!/usr/bin/env python3
"""Install the host's Docker Hub public-pull login for the ARC mirror."""

import argparse
import base64
import json
import os
import tempfile
from pathlib import Path


def credential_from_docker_config(path: Path) -> tuple[str, str]:
    auths = json.loads(path.read_text())["auths"]
    auth = auths["https://index.docker.io/v1/"]["auth"]
    username, token = base64.b64decode(auth, validate=True).decode().split(":", 1)
    if username != "strawgatepydantic" or not token or any(c.isspace() for c in token):
        raise ValueError("Expected the strawgatepydantic Docker Hub public-pull login")
    return username, token


def install(config_path: Path, output_path: Path) -> None:
    username, token = credential_from_docker_config(config_path)
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(output_path.parent, 0o700)
    fd, temporary_path = tempfile.mkstemp(prefix=".credentials-", dir=output_path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            out.write(f"REGISTRY_PROXY_USERNAME={username}\n")
            out.write(f"REGISTRY_PROXY_PASSWORD={token}\n")
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, output_path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    install(args.docker_config, args.output)
    print("Installed Docker Hub mirror credentials with mode 0600")
