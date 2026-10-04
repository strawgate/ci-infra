#!/bin/sh
# ARC 0.14.2 generates the DinD sidecar after merging Helm values, so its
# dockerd arguments cannot be changed through template.spec in values.yaml.
#
# Two changes to the sidecar:
# - dockerd pulls through the Docker Hub mirror.
# - Docker's containers run inside the runner pod's limits. A privileged
#   container gets the node's cgroup namespace, so dockerd would otherwise put
#   them in the node's /sys/fs/cgroup/docker, with no CPU or memory limit
#   (infra/arc/README.md, "DinD containment"). The wrapper below starts the
#   image's entrypoint with --cgroup-parent=<pod cgroup>/dind, caps that cgroup's
#   memory below the pod's (so a runaway container is killed, not the runner),
#   and keeps dockerd itself out of the OOM killer's way.
set -eu

WRAPPER=$(cat <<'EOF'
cg=$(sed -n 's/^0:://p' /proc/self/cgroup)
pod=${cg%/*}
if [ -n "$cg" ] && [ -d "/sys/fs/cgroup$pod" ] && mkdir -p "/sys/fs/cgroup$pod/dind"; then
  limit=$(cat "/sys/fs/cgroup$pod/memory.max")
  if [ "$limit" != max ]; then
    reserve=$((2 << 30))
    if [ $((limit / 4)) -lt "$reserve" ]; then reserve=$((limit / 4)); fi
    echo $((limit - reserve)) > "/sys/fs/cgroup$pod/dind/memory.max"
  fi
  echo -900 > /proc/self/oom_score_adj
  set -- "$@" --cgroup-parent="$pod/dind"
  echo "arc-dind: containers in $pod/dind, memory.max $(cat "/sys/fs/cgroup$pod/dind/memory.max")"
else
  echo "arc-dind: no cgroup v2 pod cgroup found; Docker's containers are not contained" >&2
fi
exec dockerd-entrypoint.sh "$@"
EOF
)
export WRAPPER

awk '
{
  print
  line = $0
  sub(/^[[:space:]]*/, "", line)
  if (line == "- --group=$(DOCKER_GROUP_GID)") {
    indent = $0
    sub(/[^[:space:]].*$/, "", indent)
    print indent "- --registry-mirror=http://192.168.122.1:5000"
    print indent "- --insecure-registry=192.168.122.1:5000"
    # The container keys sit two spaces left of the args items.
    key = substr(indent, 3)
    print key "command:"
    print indent "- sh"
    print indent "- -c"
    print indent "- |"
    n = split(ENVIRON["WRAPPER"], lines, "\n")
    for (i = 1; i <= n; i++) print indent "  " lines[i]
    print indent "- arc-dind"
    count++
  }
}
END {
  if (count != 1) {
    print "Expected exactly one ARC DinD sidecar; chart template may have changed" > "/dev/stderr"
    exit 1
  }
}
'
