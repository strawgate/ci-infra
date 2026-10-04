# Local validation; deployment is deliberate and documented in infra/arc/README.md.
check:
    actionlint -shellcheck= .github/workflows/*.yml
    shellcheck infra/arc/mirror/check.sh infra/arc/mirror/start.sh infra/arc/node/check-scale-sets.sh infra/arc/node/helm-plugins/arc-dind-mirror/render.sh
    infra/arc/node/check-scale-sets.sh
    ARC_DOCKERHUB_MIRROR_ENV_FILE=/dev/null docker compose -f infra/arc/mirror/compose.yaml config --no-env-resolution --quiet
    python3 -m unittest discover -s infra/arc/mirror -p 'test_*.py'
    just kata-check

# Explicit opt-in: renders the pilot's pinned charts without deploying anything.
kata-check:
    python3 -m unittest discover -s infra/arc/kata -p 'test_*.py'
    HELM_PLUGINS="{{justfile_directory()}}/infra/arc/node/helm-plugins" python3 infra/arc/kata/check.py
    node --check infra/arc/kata/smoke.js
    bash -n infra/arc/kata/install-worker-stopped.sh
    shellcheck infra/arc/kata/install-worker-stopped.sh
    shellcheck infra/arc/kata/firewall.sh
    shellcheck infra/arc/kata/deploy-runners.sh

kata-smoke-pod:
    HELM_PLUGINS="{{justfile_directory()}}/infra/arc/node/helm-plugins" python3 infra/arc/kata/check.py --smoke-pod

kata-agent-smoke-pod:
    HELM_PLUGINS="{{justfile_directory()}}/infra/arc/node/helm-plugins" python3 infra/arc/kata/check.py --agent-smoke-pod

# Run deliberately from the control-plane checkout with its kubeconfig.
deploy-runners:
    bash infra/arc/kata/deploy-runners.sh
