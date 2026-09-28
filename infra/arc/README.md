# ARC runner scale sets

This directory is the source for the non-secret runner images and Helm values
of the self-hosted GitHub Actions fleet. The GitHub App private key is
only stored in the `arc-github-app` Kubernetes secret and must never be added
to this repository.

| Scale set               |        Capacity | Maximum runners | Intended work                         |
| ----------------------- | --------------: | --------------: | ------------------------------------- |
| `o11yfleet-1c-4g`       |  1 vCPU / 4 GiB |               2 | lightweight coordination              |
| `o11yfleet-2c-8g`       |  2 vCPU / 8 GiB |              10 | default CI                            |
| `o11yfleet-agent-2c-8g` |  2 vCPU / 8 GiB |               1 | trusted gh-aw agent workflows         |
| `o11yfleet-4c-16g`      | 4 vCPU / 16 GiB |               5 | E2E, mutation, and deploy-gating work |

The same node also runs two scale sets for **strawgate/opamp-clients**
(`opamp-clients-2c-8g`, up to 6 runners, and `opamp-clients-4c-16g`, up to
2). strawgate is a user account, and a user account's self-hosted runners
belong to one repository, so that repository needs scale sets of its own
rather than sharing these. See [opamp-clients](#opamp-clients).

`runner/Dockerfile` extends the official ARC runner image with the runtime
tools required before a workflow can install its own dependencies: Node 22,
the GitHub CLI, `libatomic` for `pnpm/action-setup`, and `iptables` for the
gh-aw firewall. `agent-runner/Dockerfile` is a distinct same-container Docker
runner for gh-aw: its firewall chroots into the Docker daemon host and so
cannot use ARC's normal dind sidecar. It includes the Claude CLI that is
normally supplied by GitHub-hosted runner images. ARC runner templates must explicitly use
`/home/runner/run.sh`; the base image's default command is an interactive
shell and exits immediately in Kubernetes.

The agent runner container has `privileged: true` for dockerd and gh-aw's
network firewall. Standard ARC jobs also have a privileged dind sidecar.
The agent uses Docker's portable `vfs`
storage driver because nested overlayfs cannot unpack some firewall-image OCI
whiteouts. That cost is acceptable for these ephemeral, trusted workflows.

## Shared pnpm store

The 1c, 2c and 4c runner pods mount `/var/cache/o11yfleet/pnpm-store` from
the node at `/home/runner/.pnpm-store-shared`. The
`seed-runner-toolchains` action points pnpm at it (`npm_config_store_dir` in
`$GITHUB_ENV`) when the mount is present, and workflows no longer pass
`cache: pnpm` to `actions/setup-node`: that restored a 337MB store from the
Actions cache over the node's ~5MB/s uplink, 70–205s per job and slower still
when several jobs shared the link. With the store on local disk,
`pnpm install` only fetches packages the lockfile added since the store last
saw them.

Keep the opt-in in the workflow, not in the pod env. A job that still runs
`cache: pnpm` (an old branch's workflow file, a re-run of an old run) would
otherwise extract the Actions cache into the shared store while other jobs
install from it, and those installs fail when a store file vanishes
mid-copy. That happened on the first rollout. For the same reason, never combine
`cache: pnpm` with the seed step in one job.

The agent runner does not mount it. The store is writable by every job on the
other tiers, which is acceptable only because fork PRs never reach this fleet
(every job on it is guarded on the PR's head repository being this one).

The directory must exist, owned by the runner uid, before a pod mounts it.
The volume is `type: Directory`, so a missing directory fails the pod rather
than silently creating a root-owned one pnpm cannot write:

```bash
sudo install -d -o 1001 -g 1001 -m 755 /var/cache/o11yfleet/pnpm-store
```

Do not run `pnpm store prune` against it. Prune removes files that no
project hard-links to, and the runner workspaces are on a different mount, so
pnpm clones rather than links (see below) and every file looks orphaned. The store grows
only with lockfile churn. If it ever needs resetting, check its size and
clear it at a quiet moment (an install running at that instant can fail once):

```bash
sudo du -sh /var/cache/o11yfleet/pnpm-store
sudo find /var/cache/o11yfleet/pnpm-store -mindepth 1 -delete
```

### Store disk: XFS with reflink

A warm `pnpm install` spent ~34s of its ~54s copying 1,454 packages from the
store into `node_modules`. Hard links cannot help: the store and the job
workspace are separate mounts in the pod, and `link(2)` refuses to cross
mounts even on one filesystem. Copy-on-write clones can (Linux ≥5.18 allows
`FICLONE` across mounts of the same filesystem), and pnpm's default import
method tries a clone first. The VM's root disk is ext4, which has no clones,
so both the store and the kubelet directory (which holds every pod's
`emptyDir`, including the `_work` workspace) live on a second disk formatted
XFS with `reflink=1`, bind-mounted back at their usual paths:

```text
LABEL=arc-xfs /srv/arc-xfs xfs defaults,discard,nofail 0 2
/srv/arc-xfs/kubelet /var/lib/kubelet none bind,x-systemd.requires-mounts-for=/srv/arc-xfs,nofail 0 0
/srv/arc-xfs/pnpm-store /var/cache/o11yfleet/pnpm-store none bind,x-systemd.requires-mounts-for=/srv/arc-xfs,nofail 0 0
```

The disk is `/data/gha-o11yfleet/disks/o11yfleet-arc-xfs.qcow2` on
docker-host, 120G thin, attached with `discard='unmap'` so space the VM frees
goes back to the host. Clones are also safer than hard links would be: a job
that writes into `node_modules` changes its own copy, never the store.

[`node/xfs-cutover.sh`](node/xfs-cutover.sh) is the move, for rebuilding the
node. It stops k3s and every container, so drain first: set each scale set's
`maxRunners` to 0 (`kubectl patch autoscalingrunnerset … --type merge`), wait
for `arc-runners` to empty, run it, then restore the values from
`values/*.yaml`. `nofail` means a missing disk degrades to the old ext4
behaviour (plain copies) instead of blocking boot.

To confirm clones are happening, check that an installed file shares extents
with the store (`filefrag -v <file> | grep shared` inside a runner pod).

## Node: unclean reboots

The kubelet runs the static CPU manager (`reserved-cpus=0-1` in
`/etc/rancher/k3s/config.yaml`), which records each pod's pinned CPUs in
`/var/lib/kubelet/cpu_manager_state`. After an unclean reboot those pods are
gone but the file is not, and the kubelet refuses to start ("current set of
available CPUs … doesn't match with CPUs in state"). That crash-loops k3s and
takes the whole fleet down. It happened on 2026-09-23.

[`node/kubelet-cpu-state-reset.service`](node/kubelet-cpu-state-reset.service)
clears the file at boot, before k3s starts, when no containers exist. It is
installed and enabled on the node:

```bash
sudo cp infra/arc/node/kubelet-cpu-state-reset.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable kubelet-cpu-state-reset.service
```

If k3s is crash-looping on this error outside a boot, stop it, move the file
aside, and start it again:

```bash
sudo systemctl stop k3s
sudo mv /var/lib/kubelet/cpu_manager_state /var/lib/kubelet/cpu_manager_state.bak
sudo systemctl start k3s
```

The same checkpoint can also lose CPUs while the node is running. On
2026-09-28, the node advertised 46 allocatable CPUs but, after **all** runner
pods drained, `defaultCpuSet` held only 28 of the VM's 48 CPUs. New pods then
failed with `UnexpectedAdmissionError` despite apparent scheduler capacity.
Check both the running pods and `cpu_manager_state`; do not infer a leak from
the scheduler's numbers alone. Recovery was: temporarily set every scale
set's `maxRunners` to 0, wait for runner pods to finish, stop k3s, move the
checkpoint to a dated backup, start k3s, verify `defaultCpuSet` is `0-47`,
then restore the original scale-set limits. Never reset the checkpoint while
runner pods are active. If this recurs, investigate the v1.36 pod-level CPU
manager before making a restart timer: a timed restart would kill CI jobs.

## opamp-clients

`values/opamp-clients-*.yaml` point at `https://github.com/strawgate/opamp-clients`
and run `opamp-clients-runner/Dockerfile`. That image uses the pinned official
ARC base and adds what that repository's jobs expected of GitHub-hosted
`ubuntu-latest`:

- Rust (the version in its `rust-toolchain.toml`, with clippy, rustfmt and
  the wasm target), installed as the runner user so jobs can add nightly;
- a C toolchain;
- Python;
- Maven;
- ICU, for .NET.

It has no pnpm store mount: that repository doesn't use pnpm.

Its jobs share the node with this fleet's. The caps (6 and 2 runners) keep a
full opamp-clients run (about 25 jobs per push) from starving o11yfleet's CI.
Past the caps its jobs queue. Pods also stay Pending when the node is full,
whichever repository they belong to.

One-time setup:

1. Give the ARC GitHub App access to strawgate/opamp-clients. In GitHub:
   Settings → Applications → the ARC app → Configure → Repository access, add
   the repository. The installation, and so the `arc-github-app` secret,
   stays the same.
2. Install the two scale sets:

   ```bash
   for tier in 2c-8g 4c-16g; do
     sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm install "opamp-clients-${tier}" \
       oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
       --version 0.14.2 --namespace arc-runners \
       --values "infra/arc/values/opamp-clients-${tier}.yaml" --wait
   done
   ```

3. Confirm the scale sets exist:
   `sudo k3s kubectl get autoscalingrunnersets -n arc-runners`.
   They should also appear under the repository's Settings → Actions → Runners.

To update, bump the tag in both `values/opamp-clients-*.yaml` files and run
`helm upgrade`, as with the others below.

## Deploying an image update

The images are built and published by `.github/workflows/build-runner-images.yml`
on any push to `main` touching one of the three runner image directories,
and on demand via `gh workflow run build-runner-images.yml`. The run summary
prints the exact `image:` line to paste.

It runs on GitHub-hosted runners, not the ARC fleet — deliberately, so the
images can still be rebuilt when the fleet is down or the current image is
broken. Building them on the runners they replace would be circular.

The workflow deliberately stops at publishing. These images run the fleet, so
an auto-deployed bad one would take out the runners needed to build the fix.

### One-time: let the node pull from GHCR

The packages inherit this repository's private visibility, so k3s needs a pull
secret. Use a PAT with `read:packages` only — not the ARC GitHub App key, whose
tokens expire hourly and cannot back a static secret.

```bash
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create secret docker-registry ghcr \
  --docker-server=ghcr.io \
  --docker-username=strawgate \
  --docker-password="$GHCR_READ_PACKAGES_PAT" \
  --namespace arc-runners
```

### Each update

Bump the tag in all four o11yfleet values files and apply (for the
opamp-clients ones, see [opamp-clients](#opamp-clients)). No build on the node, and no
`docker save | k3s ctr images import` — k3s pulls the published image.

```bash
for tier in 1c-4g 2c-8g 4c-16g agent-2c-8g; do
  sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade "o11yfleet-${tier}" \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
    --version 0.14.2 --namespace arc-runners \
    --values "infra/arc/values/${tier}.yaml" --wait
done
```

Tags are immutable (`<date>-<short-sha>`), so `imagePullPolicy: IfNotPresent`
still fetches a new one while never re-pulling an existing one.

To build locally for debugging — note this is the same context the workflow
uses, so it reproduces exactly:

```bash
docker build --platform linux/amd64 -t o11yfleet-arc-runner:dev infra/arc/runner
```

Use `sudo k3s kubectl get ephemeralrunners,pods -n arc-runners` to confirm
that a job receives a runner and that the Pod is removed after the job.
