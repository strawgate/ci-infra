FROM ghcr.io/actions/actions-runner@sha256:e5496277be5d09bc968b3d64911b74e219ac4a3f2edce956a3ecf9271bea1ef4

USER root

ARG NODE_VERSION=22.23.2
ARG RUST_VERSION=1.95.0

# JavaScript actions need a baseline Node binary before setup-node runs. Docker
# talks to ARC's dind sidecar; there is no daemon in this image.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential ca-certificates clang cmake curl docker.io iptables libatomic1 libicu-dev libssl-dev maven pkg-config python3 python3-venv unzip xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && node_archive="node-v${NODE_VERSION}-linux-x64.tar.xz" \
    && curl --fail --location --retry 3 --output "/tmp/${node_archive}" "https://nodejs.org/dist/v${NODE_VERSION}/${node_archive}" \
    && tar --extract --xz --file "/tmp/${node_archive}" --directory /opt \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/node" /usr/local/bin/node \
    && ln --symbolic --force "/opt/node-v${NODE_VERSION}-linux-x64/bin/npm" /usr/local/bin/npm \
    && rm "/tmp/${node_archive}"

USER runner
ENV PATH="/home/runner/.cargo/bin:${PATH}"
RUN curl --proto '=https' --tlsv1.2 --fail --silent --show-error https://sh.rustup.rs \
    | sh -s -- -y --profile minimal --default-toolchain "${RUST_VERSION}" --no-modify-path --component clippy,rustfmt --target wasm32-unknown-unknown \
    && cargo --version \
    && rustc --version
