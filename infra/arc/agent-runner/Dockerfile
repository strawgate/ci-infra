FROM ghcr.io/actions/actions-runner@sha256:e5496277be5d09bc968b3d64911b74e219ac4a3f2edce956a3ecf9271bea1ef4

USER root

ARG NODE_VERSION=22.23.2
ARG CLAUDE_CODE_VERSION=2.1.278

# gh-aw's firewall chroots into the Docker daemon host. Keeping dockerd and
# the Actions runner in this one image gives the chroot the runner's Node and
# tool cache, unlike the standard ARC dind sidecar topology.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl docker.io docker-compose-v2 gh iptables libatomic1 libcap2-bin xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && node_archive="node-v${NODE_VERSION}-linux-x64.tar.xz" \
    && curl --fail --location --retry 3 --output "/tmp/${node_archive}" "https://nodejs.org/dist/v${NODE_VERSION}/${node_archive}" \
    && tar --extract --xz --file "/tmp/${node_archive}" --directory /opt \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/node" /usr/local/bin/node \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/npm" /usr/local/bin/npm \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/npx" /usr/local/bin/npx \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/corepack" /usr/local/bin/corepack \
    && npm install --global "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/claude" /usr/local/bin/claude \
    && rm "/tmp/${node_archive}"

COPY start-dockerd.sh /usr/local/bin/start-dockerd.sh
RUN chmod 0755 /usr/local/bin/start-dockerd.sh

USER runner
