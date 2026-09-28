#!/usr/bin/env bash
set -euo pipefail

# ARC dind uses a separate container, but gh-aw's chroot mode deliberately
# needs Docker's host filesystem to be this runner filesystem. vfs avoids the
# overlay-on-overlay whiteout limitation inside the k3s VM.
sudo dockerd --host=unix:///var/run/docker.sock --group=123 --storage-driver=vfs >/tmp/dockerd.log 2>&1 &

for _ in $(seq 1 60); do
  if docker info >/dev/null 2>&1; then
    exec /home/runner/run.sh
  fi
  sleep 1
done

cat /tmp/dockerd.log >&2 || true
exit 1
