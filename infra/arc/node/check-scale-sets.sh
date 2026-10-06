#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
export HELM_PLUGINS="$repo_root/infra/arc/node/helm-plugins"

render_scale_set() {
  local values=$1
  shift
  helm template "$(basename "$values" .yaml)" \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
    --version 0.14.2 --namespace arc-runners --values "$values" \
    "$@" | python3 "$repo_root/infra/arc/kata/check-fleet.py"
}

for values in "$repo_root"/infra/arc/values/*.yaml; do
  render_scale_set "$values" --post-renderer arc-kata
done
