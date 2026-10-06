#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
kubectl wait node/docker-host-kata --for=condition=Ready --timeout=30s
[[ $(kubectl get runtimeclass kata-clh-runtime-rs -o jsonpath='{.handler}') == kata-clh-runtime-rs ]]
# Existing agent daemons keep their configuration until their jobs finish;
# newly created agent pods read this file when dockerd starts.
kubectl apply -f "$repo_root/infra/arc/node/docker-daemon-configmap.yaml"
if [[ $(helm version --short) == v4.* ]]; then
  export HELM_PLUGINS="$repo_root/infra/arc/node/helm-plugins"
  renderer=arc-kata
else
  renderer="$repo_root/infra/arc/node/helm-plugins/arc-kata/render.py"
fi
for values in "$repo_root"/infra/arc/values/*.yaml; do
  name=$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["runnerScaleSetName"])' "$values")
  helm upgrade --install "$name" \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
    --version 0.14.2 --namespace arc-runners --values "$values" \
    --post-renderer "$renderer" --wait --timeout 2m
done
