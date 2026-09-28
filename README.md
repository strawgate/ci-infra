# CI infrastructure

Private configuration for the self-hosted GitHub Actions fleet on `docker-host`.
This repository owns the ARC runner images, pinned Helm values, k3s node
maintenance, and host systemd units. Application workflows and their `runs-on`
choices remain in [o11yfleet](https://github.com/strawgate/o11yfleet) and
[opamp-clients](https://github.com/strawgate/opamp-clients).

The fleet is an `o11yfleet-arc` VM on `docker-host`, running k3s and ARC 0.14.2.
The runner scale sets are repository scoped: the two private repositories
have distinct scale sets even though they share one node. Their listeners use
the existing `arc-github-app` Kubernetes Secret; image pulls use the `ghcr`
Secret. Neither credential belongs in Git.

## Layout

- `infra/arc/runner`, `agent-runner`, `opamp-clients-runner`: image sources.
- `infra/arc/values`: source of truth for the Helm releases.
- `infra/arc/node`: VM-side recovery and disk setup.
- `infra/arc/README.md`: deployment and recovery runbook.
- `host/systemd`: weekly bounded Docker pruning on the bare-metal host.

Runner images build on a GitHub-hosted runner so the fleet can be repaired if
it cannot run jobs. Builds publish immutable tags; updating a Helm value and
deploying it is a separate, deliberate step. Run `just check` before changing
the fleet. Do not put GitHub App keys, GHCR tokens, kubeconfigs, or VM images
in this repository.
