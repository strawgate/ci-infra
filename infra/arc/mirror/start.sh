#!/bin/sh
set -eu

for attempt in $(seq 1 60); do
  if /usr/sbin/ip -4 addr show dev virbr0 2>/dev/null | grep -Fq 'inet 192.168.122.1/24'; then
    exec /usr/bin/docker compose \
      -f /data/gha-o11yfleet/arc-dockerhub-mirror/compose.yaml \
      up -d --wait --wait-timeout 60
  fi
  sleep 2
done

printf 'ARC libvirt bridge 192.168.122.1 did not become ready after %s attempts\n' "$attempt" >&2
exit 1
