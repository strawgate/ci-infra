# Local validation; deployment is deliberate and documented in infra/arc/README.md.
check:
    actionlint -shellcheck= .github/workflows/*.yml
    for values in infra/arc/values/*.yaml; do helm template "$(basename "$values" .yaml)" oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set --version 0.14.2 --namespace arc-runners --values "$values" >/dev/null; done
