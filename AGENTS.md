# CI infrastructure work

- Run `just check` before proposing changes. Its Helm chart and version must
  match the live release before any upgrade.
- Keep GitHub App keys, GHCR tokens, kubeconfigs, and host credentials out of
  Git. Helm values reference existing Kubernetes Secrets by name.
- Build runner images on GitHub-hosted runners, never on the fleet they
  replace. An image build must remain possible when ARC is unavailable.
- Deploy immutable image tags deliberately; publishing alone does not update
  a running scale set. Verify the new pod pulls and runs a job before retiring
  the old image or source.
- Before k3s maintenance, set every scale set's `maxRunners` to zero and wait
  for all runner pods to finish. Never reset CPU-manager state under live jobs.
- On `docker-host`, do not prune Docker volumes or containers as part of the
  weekly cache/image timer. Only touch stacks owned by the current task.
