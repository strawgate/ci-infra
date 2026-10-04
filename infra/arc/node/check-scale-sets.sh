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
    "$@" >/dev/null
}

for values in "$repo_root"/infra/arc/values/*.yaml; do
  if [[ "$values" == *agent-2c-8g.yaml || "$values" == *opamp-clients-1c-2g.yaml ]]; then
    render_scale_set "$values"
  else
    render_scale_set "$values" --post-renderer arc-dind-mirror
  fi
done
