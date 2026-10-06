"""Transfer the existing VM's agent join token locally; never log the token."""
import base64
import json
import os
import pathlib
import subprocess
import time


def agent(request):
    result = subprocess.check_output([
        "virsh", "-c", "qemu:///system", "qemu-agent-command",
        "o11yfleet-arc", json.dumps(request),
    ], text=True)
    return json.loads(result)["return"]


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo on docker-host")
    path = pathlib.Path("/etc/rancher/k3s/arc-join-token")
    if path.exists():
        raise SystemExit("Join token already exists; refusing to overwrite it")
    started = agent({"execute": "guest-exec", "arguments": {
        "path": "/bin/cat", "arg": ["/var/lib/rancher/k3s/server/agent-token"],
        "capture-output": True,
    }})
    for _ in range(40):
        result = agent({"execute": "guest-exec-status", "arguments": {"pid": started["pid"]}})
        if result["exited"]:
            if result.get("exitcode") != 0:
                raise SystemExit("Could not read the VM's agent token")
            token = base64.b64decode(result["out-data"])
            if not token.strip().startswith(b"K10"):
                raise SystemExit("Unexpected agent token format")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(token)
            print("Agent token installed root-owned, mode 0600; value not displayed")
            return
        time.sleep(0.25)
    raise SystemExit("Guest agent did not complete the token read")


if __name__ == "__main__":
    main()
