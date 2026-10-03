# Local validation; deployment is deliberate and documented in infra/arc/README.md.
check:
    actionlint -shellcheck= .github/workflows/*.yml
    shellcheck infra/arc/mirror/check.sh infra/arc/mirror/start.sh infra/arc/node/check-scale-sets.sh infra/arc/node/helm-plugins/arc-dind-mirror/render.sh
    infra/arc/node/check-scale-sets.sh
    ARC_DOCKERHUB_MIRROR_ENV_FILE=/dev/null docker compose -f infra/arc/mirror/compose.yaml config --no-env-resolution --quiet
    python3 -m unittest discover -s infra/arc/mirror -p 'test_*.py'
