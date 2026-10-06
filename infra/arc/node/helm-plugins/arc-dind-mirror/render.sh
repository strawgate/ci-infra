#!/bin/sh
# ARC 0.14.2 generates the DinD sidecar after merging Helm values, so its
# image and dockerd arguments cannot be changed through template.spec in
# values.yaml.
#
# Three changes to the sidecar:
# - dockerd pulls through the Docker Hub mirror.
# - Its bridges take the pod network's MTU (flannel's VXLAN: 1450), not
#   Docker's default 1500. A container on a 1500 bridge asks servers for
#   packets the pod's network can't carry; where the "too big" reply doesn't
#   come back, the download stalls for ever (infra/arc/README.md, "DinD MTU").
# - It runs our image (infra/arc/dind) through `arc-dind-start`, which keeps
#   Docker's containers inside the runner pod's limits and gives each the pod's
#   CPU count (infra/arc/README.md, "DinD containment").
set -eu

DIND_IMAGE=ghcr.io/strawgate/ci-infra-arc-dind:20261004-e0fda7a

DIND_IMAGE=$DIND_IMAGE awk '
{
  line = $0
  sub(/^[[:space:]]*/, "", line)
  if (line == "- name: dind") {
    in_dind = 1
  } else if (line ~ /^- name: /) {
    in_dind = 0
  }
  if (in_dind && line == "args:") {
    key = $0
    sub(/[^[:space:]].*$/, "", key)
  }
  if (in_dind && line == "image: docker:dind") {
    indent = $0
    sub(/[^[:space:]].*$/, "", indent)
    print indent "image: " ENVIRON["DIND_IMAGE"]
    images++
    next
  }
  print
  if (line == "- --group=$(DOCKER_GROUP_GID)") {
    indent = $0
    sub(/[^[:space:]].*$/, "", indent)
    print indent "- --registry-mirror=http://192.168.122.1:5000"
    print indent "- --insecure-registry=192.168.122.1:5000"
    print indent "- --mtu=1450"
    print indent "- --default-network-opt=bridge=com.docker.network.driver.mtu=1450"
    # At the indent of the sidecar args key (Helm 3 indents list items
    # under their key, Helm 4 does not).
    print key "command:"
    print indent "- arc-dind-start"
    count++
  }
}
END {
  if (count != 1 || images != 1) {
    print "Expected exactly one ARC DinD sidecar (image docker:dind); chart template may have changed" > "/dev/stderr"
    exit 1
  }
}
'
