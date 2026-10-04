# The DinD sidecar of the ARC runner pods: docker:dind, plus what keeps Docker's
# containers inside the runner pod (infra/arc/README.md, "DinD containment").
# The post-renderer (infra/arc/node/helm-plugins/arc-dind-mirror/render.sh)
# puts this image and `arc-dind-start` on the chart's sidecar.
FROM docker:29.8.2-dind@sha256:7dcdfc4a20246236f558175182ccace1eb15a41bd3eb119dd2284f393498b7c1

RUN apk add --no-cache jq

COPY arc-dind-start arc-runc /usr/local/bin/
COPY arc-runc.jq /usr/local/share/arc-dind/arc-runc.jq
