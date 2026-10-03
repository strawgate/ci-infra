#!/bin/sh
set -eu

cache_dir=/data/gha-o11yfleet/dockerhub-mirror
mirror_url=http://192.168.122.1:5000/v2/
max_cache_bytes=53687091200 # 50 GiB; investigate before manually running stop-the-world GC.
min_free_bytes=214748364800 # Keep at least 200 GiB free on the ARC SSD.

curl --fail --silent --show-error --max-time 10 "$mirror_url" >/dev/null
cache_bytes=$(du -sB1 "$cache_dir" | awk '{print $1}')
free_bytes=$(df -B1 --output=avail "$cache_dir" | awk 'END {print $1}')
printf 'ARC Docker Hub mirror: cache=%s bytes, SSD free=%s bytes\n' "$cache_bytes" "$free_bytes"

if [ "$cache_bytes" -gt "$max_cache_bytes" ] || [ "$free_bytes" -lt "$min_free_bytes" ]; then
  printf 'ARC Docker Hub mirror needs capacity review; do not prune live Docker data\n' >&2
  exit 1
fi
