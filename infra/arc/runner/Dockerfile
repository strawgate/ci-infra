# Deliberately refresh this digest after proving the candidate can claim a job.
FROM ghcr.io/actions/actions-runner@sha256:e5496277be5d09bc968b3d64911b74e219ac4a3f2edce956a3ecf9271bea1ef4

USER root

ARG NODE_VERSION=22.23.2
# Keep in step with tests/oracle/go.mod.
ARG GO_VERSION=1.24.0
# Keep in step with @playwright/test in tests/ui and apps/site-portal. If they
# drift, Playwright re-downloads at runtime: slower, never broken.
ARG PLAYWRIGHT_VERSION=1.63.0

# pnpm/action-setup's bundled executable needs libatomic. GitHub actions that
# invoke JavaScript before actions/setup-node also require a baseline `node`.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl docker-compose-v2 gh iptables libatomic1 xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && node_archive="node-v${NODE_VERSION}-linux-x64.tar.xz" \
    && curl --fail --location --retry 3 --output "/tmp/${node_archive}" "https://nodejs.org/dist/v${NODE_VERSION}/${node_archive}" \
    && tar --extract --xz --file "/tmp/${node_archive}" --directory /opt \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/node" /usr/local/bin/node \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/npm" /usr/local/bin/npm \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/npx" /usr/local/bin/npx \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/corepack" /usr/local/bin/corepack \
    && rm "/tmp/${node_archive}"

# Go, for tests/oracle. actions/setup-go looks only in the Actions tool cache,
# same as setup-node, so .github/actions/seed-runner-toolchains links this in.
# Measured cost of NOT baking it: 36s per job that needs Go.
RUN set -eux \
    && go_archive="go${GO_VERSION}.linux-amd64.tar.gz" \
    && curl --fail --location --retry 3 --output "/tmp/${go_archive}" "https://go.dev/dl/${go_archive}" \
    && mkdir -p "/opt/go-${GO_VERSION}" \
    && tar --extract --gzip --file "/tmp/${go_archive}" --directory "/opt/go-${GO_VERSION}" --strip-components=1 \
    && rm "/tmp/${go_archive}" \
    && "/opt/go-${GO_VERSION}/bin/go" version

# Playwright browsers AND their system libraries. This is the expensive one:
# the test job spent 67s restoring a 278MB browser cache plus 64s running
# `playwright install-deps` (apt) on EVERY run. Baked into the image both
# disappear -- the layer is already on the node, so there is no per-job
# transfer at all.
#
# PLAYWRIGHT_BROWSERS_PATH is already in turbo.json's globalPassThroughEnv, so
# the value reaches every task. ci.yml keys its cache steps off this directory
# existing, which means a runner WITHOUT this layer keeps the old behaviour.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN set -eux \
    && npx --yes "playwright@${PLAYWRIGHT_VERSION}" install --with-deps chromium chromium-headless-shell \
    && rm -rf /var/lib/apt/lists/* /root/.npm \
    && chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"

USER runner
