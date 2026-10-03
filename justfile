# Local validation; deployment is deliberate and documented in infra/arc/README.md.
check:
    actionlint -shellcheck= .github/workflows/*.yml
    infra/arc/node/check-scale-sets.sh
    docker compose -f infra/arc/mirror/compose.yaml config --no-env-resolution --quiet
    python3 -m unittest discover -s infra/arc/mirror -p 'test_*.py'
