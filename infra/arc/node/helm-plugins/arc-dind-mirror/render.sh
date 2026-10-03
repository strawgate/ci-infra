#!/bin/sh
# ARC 0.14.2 generates the DinD sidecar after merging Helm values, so its
# dockerd arguments cannot be changed through template.spec in values.yaml.
set -eu

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
