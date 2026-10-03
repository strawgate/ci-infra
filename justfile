# Local validation; deployment is deliberate and documented in infra/arc/README.md.
check:
    actionlint -shellcheck= .github/workflows/*.yml
    infra/arc/node/check-scale-sets.sh
    ARC_DOCKERHUB_MIRROR_ENV_FILE=/dev/null docker compose -f infra/arc/mirror/compose.yaml config --no-env-resolution --quiet
    python3 -m unittest discover -s infra/arc/mirror -p 'test_*.py'
