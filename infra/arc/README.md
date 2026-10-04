# ARC runner scale sets

The live fleet now runs on the bare-metal Kata worker. Use
[Kata deployment and rollback](kata/README.md) and `just deploy-runners`
for all scale-set upgrades. The non-Kata deployment commands below describe
the previous VM topology and must not be used for the active fleet.

This directory is the source for the non-secret runner images and Helm values
of the self-hosted GitHub Actions fleet. The GitHub App private key is
only stored in the `arc-github-app` Kubernetes secret and must never be added
to this repository.

| Scale set               |        Capacity | Maximum runners | Intended work                         |
| ----------------------- | --------------: | --------------: | ------------------------------------- |
| `o11yfleet-1c-4g`       |  1 vCPU / 4 GiB |               2 | lightweight coordination              |
| `o11yfleet-2c-8g`       |  2 vCPU / 8 GiB |              10 | default CI                            |
| `o11yfleet-agent-2c-8g` |  2 vCPU / 8 GiB |               1 | trusted gh-aw agent workflows         |
| `o11yfleet-4c-8g`       |  4 vCPU / 8 GiB |               2 | UI and collector E2E memory trial     |
| `o11yfleet-4c-16g`      | 4 vCPU / 16 GiB |               6 | E2E, mutation, and deploy-gating work |

The same node also runs three scale sets for **strawgate/opamp-clients**:
`opamp-clients-1c-2g` (up to 2), `opamp-clients-2c-8g` (up to 8), and
`opamp-clients-4c-16g` (up to 7). strawgate is a user account, and a user
account's self-hosted runners
belong to one repository, so that repository needs scale sets of its own
rather than sharing these. See [opamp-clients](#opamp-clients).

`o11yfleet-4c-8g` is a bounded memory trial for UI regression and
collector E2E suites. SDK image builds and other heavy jobs retain the
`o11yfleet-4c-16g` default. UI artifact capture also retains that default
until artifact mode is separately qualified. The image, pnpm store, Docker Hub mirror, and
Guaranteed CPU placement match the larger pool. Its two-runner cap limits
the initial trial; the node's resource reservations still bound total fleet
concurrency. Compare full-job completion and duration, plus pod-level
`memory.events`, before moving any additional job types. Roll back routing
to `o11yfleet-4c-16g` on OOMs or material slowdowns. Install `values/4c-8g.yaml`
with the pinned chart and DinD mirror post-renderer before merging routing.

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

The ARC VM has 56 vCPUs as of 2026-09-28, leaving 16 of the host's 72 logical
CPUs outside the VM. K3s should report 56 capacity and 54 allocatable CPUs.
Changing the VM's vCPU count requires draining the runner scale sets before
restarting the VM; the static CPU manager does not support live CPU hotplug.

[`node/kubelet-cpu-state-reset.service`](node/kubelet-cpu-state-reset.service)
clears the file at boot, before k3s starts, when no containers exist. It is
installed and enabled on the node. It must wait for `/var/lib/kubelet` to
mount: the XFS bind mount is marked `nofail`, so `local-fs.target` alone can
finish first. During the 56-vCPU resize, the old unit ran before that mount
and left the real checkpoint untouched, preventing K3s from starting until
the checkpoint was moved aside. Install the corrected unit with:

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
That `0-47` check was for the former 48-vCPU VM; after the resize, an empty
node's expected `defaultCpuSet` is `0-55`.

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

The 1-core pool runs change detection, requirements, Python checker tests,
and shell result gates. These jobs need no Docker daemon, so its template
omits `containerMode: dind`. Its CPU and memory requests equal its limits
(1 vCPU and 2 GiB), preserving the static CPU manager's allocation while
reserving less memory than a conformance runner. Proofs and conformance
remain on the 2-core and 4-core pools.

Each OpAMP runner also sets
[`PYTHON_CPU_COUNT`](https://docs.python.org/3.13/using/cmdline.html#envvar-PYTHON_CPU_COUNT)
to its CPU allocation. Python 3.13 and newer honor this when code asks
`os.cpu_count()`, which otherwise
reports all 56 VM CPUs despite the runner's affinity. This also bounds older
branches' proof scripts as new runner pods start. Python versions before
3.13 need the affinity-aware worker count in the repository's scripts.

Its jobs share the node with this fleet's. The 2-core cap is 8, and the 4-core
cap is 7. The pod-level CPU and memory requests
remain equal to their limits, so Kubernetes leaves excess runner pods Pending
when the node is full. Watch o11yfleet queue time and node scheduling during
overlapping runs. Past
the caps, jobs remain queued at GitHub.

As of 2026-10-04, `opamp-clients-4c-16g` is trialing **4 CPUs / 12 GiB**;
the existing runner label is retained so workflows need no routing change.
Both memory requests and limits are 12 GiB, preserving Guaranteed QoS and
dedicated CPU placement. The seven-runner cap from main, image, and other pools
are preserved. This saves 4 GiB of scheduling reservation per new runner (28 GiB
at the cap); existing jobs retain their original resources until completion.
Observed pod peaks included substantial file cache, so judge the trial by
full-job completion, duration, and cgroup `memory.events`, not peak usage
alone. Roll back both memory values to 16 GiB if jobs OOM or slow materially.

A 2-core trial at 10 (2026-09-28) was rolled back the next day. From about
20:20 UTC that day, o11yfleet's end-to-end suites timed out on every run:
opamp-clients conformance jobs on the node went from 5-10 an hour to 50-60,
node load reached 40-90 on 56 vCPUs, and one 4 KiB fsync on the shared qcow2
disk took 16-390 ms (strawgate/o11yfleet#3059 moved the local worker state to
/dev/shm to cope). Disk, not CPU, is what this node runs out of first; raise a
cap only with a look at `io.pressure` during overlapping runs.

One-time setup:

1. Give the ARC GitHub App access to strawgate/opamp-clients. In GitHub:
   Settings → Applications → the ARC app → Configure → Repository access, add
   the repository. The installation, and so the `arc-github-app` secret,
   stays the same.
2. Install the three scale sets:

   Install the lightweight pool without the DinD post-renderer:

   ```bash
   sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade --install opamp-clients-1c-2g \
     oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
     --version 0.14.2 --namespace arc-runners \
     --values infra/arc/values/opamp-clients-1c-2g.yaml --wait
   ```

   Install the two Docker-backed pools with the post-renderer:

   ```bash
   for tier in 2c-8g 4c-16g; do
     sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm install "opamp-clients-${tier}" \
       oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
       --version 0.14.2 --namespace arc-runners \
       --values "infra/arc/values/opamp-clients-${tier}.yaml" \
       --post-renderer /usr/local/libexec/arc-dind-mirror-post-render --wait
   done
   ```

3. Confirm the scale sets exist:
   `sudo k3s kubectl get autoscalingrunnersets -n arc-runners`.
   They should also appear under the repository's Settings → Actions → Runners.

To update, bump the tag in all three `values/opamp-clients-*.yaml` files and
run `helm upgrade`. The lightweight pool uses the native Helm command above;
the two Docker-backed pools need the DinD post-renderer.

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

### Shared Docker Hub pull-through cache

The `dind` runner pods also pull Docker Hub's `docker:dind` image. Their
`imagePullSecrets` include `dockerhub-public-pulls`, a
`kubernetes.io/dockerconfigjson` secret in `arc-runners` backed by a Docker Hub
**public-read-only** token. Create the secret on the node before upgrading the
scale sets. Never commit the token or put it in Helm values.

The pull secret authenticates **k3s image pulls only**. Each job's Docker daemon
is ephemeral, so a second runner would otherwise download the same Hub layers
again. One Distribution registry on `docker-host` caches public Hub images for
all runner daemons. It binds only to the libvirt bridge
(`192.168.122.1:5000`), stores data on the ARC SSD at
`/data/gha-o11yfleet/dockerhub-mirror`, and uses the same public-read-only
Docker Hub login upstream. It does not cache GHCR or pnpm packages, and each
active daemon still needs its own local layers to run containers.

Workflow `docker/login-action` steps authenticate directly to Docker Hub, not
through the mirror. Their repository `DOCKERHUB_TOKEN` secret and
`DOCKERHUB_USERNAME` variable are separate from the mirror credentials and the
k3s pull secret; rotating one does not update the others. The username must
match the token's Docker Hub account (`strawgatepydantic` for this fleet).

On `docker-host`, copy `infra/arc/mirror/{compose.yaml,config.yml,install-credentials.py,check.sh,start.sh}`
to `/data/gha-o11yfleet/arc-dockerhub-mirror/`. The host Docker CLI must first
be logged in as `strawgatepydantic`. Then install the mirror (the credential
file is root-owned mode 0600 and must never be committed):

```bash
sudo install -d -m 0750 /data/gha-o11yfleet/dockerhub-mirror
sudo python3 /data/gha-o11yfleet/arc-dockerhub-mirror/install-credentials.py \
  --docker-config /home/weaston/.docker/config.json \
  --output /etc/arc-dockerhub-mirror/credentials.env
sudo install -d -m 0755 /usr/local/libexec
sudo install -m 0755 /data/gha-o11yfleet/arc-dockerhub-mirror/start.sh \
  /usr/local/libexec/start-arc-dockerhub-mirror
sudo install -m 0644 /data/gha-o11yfleet/arc-dockerhub-mirror/arc-dockerhub-mirror.service \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now arc-dockerhub-mirror.service
curl -fsS http://192.168.122.1:5000/v2/
```

ARC 0.14.2 injects the DinD sidecar after merging Helm values, so ordinary
`template.spec` values cannot change its `dockerd` arguments. The pinned-chart
post-renderer at `infra/arc/node/helm-plugins/arc-dind-mirror/render.sh` adds
the mirror arguments, swaps the sidecar's image for `ci-infra-arc-dind`
(`infra/arc/dind`) started by `arc-dind-start` (see
[DinD containment](#dind-containment)), and fails if the chart's expected
sidecar changes. Bump `DIND_IMAGE` in `render.sh` for a new image. Install
it in the ARC VM as `/usr/local/libexec/arc-dind-mirror-post-render`, mode 0755,
and **include `--post-renderer` on every DinD Helm install/upgrade**. The VM
uses Helm 3 (an executable path); Helm 4 validation uses the adjacent plugin
manifest and `HELM_PLUGINS`. `just check` renders all five DinD scale sets.

The gh-aw agent pool runs `dockerd` in its runner container instead. Apply
`infra/arc/node/docker-daemon-configmap.yaml` in `arc-runners` before upgrading
that pool; its values mount the mirror config at `/etc/docker/daemon.json`.

Distribution expires stale cache content after seven days and requires
`storage.delete.enabled: true` for its cleanup scheduler. Do not run a blind
Docker prune: it would affect unrelated stacks and the registry already ages
out old cache entries. The weekly `dockerhub-mirror-check.timer` checks health,
cache size (50 GiB review threshold), and free SSD space (200 GiB threshold).
Copy the service/timer from `infra/arc/node/` alongside the mirror files on
`docker-host`, then install them:

```bash
sudo install -d -m 0755 /usr/local/libexec
sudo install -m 0755 /data/gha-o11yfleet/arc-dockerhub-mirror/check.sh \
  /usr/local/libexec/check-arc-dockerhub-mirror
sudo install -m 0644 /data/gha-o11yfleet/arc-dockerhub-mirror/dockerhub-mirror-check.service \
  /etc/systemd/system/
sudo install -m 0644 /data/gha-o11yfleet/arc-dockerhub-mirror/dockerhub-mirror-check.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dockerhub-mirror-check.timer
sudo systemctl start dockerhub-mirror-check.service
```

If the cache grows despite expiry,
investigate and arrange a quiet, registry-offline garbage collection pass;
Distribution garbage collection is not safe against concurrent writes.

### DinD containment

containerd gives a privileged container the node's cgroup namespace, so the
DinD sidecar sees the node's cgroup root. Left alone, `dockerd` puts every
container it starts in the node's `/sys/fs/cgroup/docker/<id>`: outside the
runner pod, with no CPU or memory limit, all 56 CPUs, and invisible to
Kubernetes. Measured on 2026-10-04: that cgroup had used ~36 CPU-hours in 21
hours, and held 81 leaked container cgroups. The image's own cgroup-v2 setup
also runs against the node's root (it created `/sys/fs/cgroup/init` there).

The sidecar runs our image, `infra/arc/dind` (`docker:dind` plus `jq` and
three files), through `arc-dind-start`, which before the image's entrypoint:

- reads the sidecar's cgroup and starts `dockerd --cgroup-parent=<pod>/dind`,
  so containers are siblings of the pod's own containers, under the pod's
  `cpu.max` and `memory.max`;
- sets `<pod>/dind/memory.max` to the pod's limit less 2 GiB (or less a
  quarter, for pods under 8 GiB). Without a limit of its own, a container that
  fills the pod triggers a pod-wide OOM, and the kernel picks the runner
  (kubelet gives a Burstable pod's processes `oom_score_adj` ~991, Docker its
  containers 0, and `memory.oom.group` kills the whole runner container). With
  it, only processes under `dind` are candidates;
- sets `dockerd`'s `oom_score_adj` to -900, so a pod-wide OOM doesn't take the
  daemon (and, by `memory.oom.group`, the whole sidecar);
- makes `arc-runc` dockerd's default runtime: runc, except that a container
  that sets no CPU quota of its own is created with the pod's (`arc-runc.jq`),
  and with `GOMAXPROCS` and `PYTHON_CPU_COUNT` set to the pod's CPU count unless
  it sets them. A container's cgroup namespace starts at the container, so it
  can't see the pod's quota; its own is what runtimes read.

What a container reports, measured in a contained 2-CPU pod on 2026-10-04:

| The container has | Go 1.25 | Java 21 | Node 22 | Python `process_cpu_count` / `cpu_count` | `nproc` |
|---|---|---|---|---|---|
| nothing (containment alone) | 56 | 56 | 56 | 56 / 56 | 56 |
| its own quota (`arc-runc`, or `--cpus 2`) | 2 | 2 | 2 | 56 / 56 | 56 |
| `--cgroupns host` | 56 | 2 | 2 | 56 / 56 | 56 |
| `--cpuset-cpus 0-1` | 2 | 2 | 2 | 2 / 56 | 2 |

So Python reads `PYTHON_CPU_COUNT` (3.13+), Go before 1.25 reads `GOMAXPROCS`,
and `nproc` (affinity only) still says 56: only pinning changes it. In the
runner container itself kubelet already sets the pod's quota on the
container's cgroup, so the values files only add the same two variables.

Tested in throwaway pods (2 CPU, 4 and 8 GiB): four busy-loop containers held
to ~1.9 CPUs, and `docker build` steps too; a 6 GiB allocation killed only its
container; the pod's cgroup tree is removed on delete even with a container
running. `infra/arc/dind/test_arc_runc.py` covers the runtime wrapper.

To check a runner: `kubectl logs <pod> -c dind | grep arc-dind` prints the
cgroup and limits; nothing new should appear under the node's
`/sys/fs/cgroup/docker`; OOM kills show in `<pod cgroup>/dind/memory.events`.
The gh-aw agent pool runs `dockerd` in its runner container and is not
covered.

### Each update

Bump the tag in all four o11yfleet values files and apply (for the
opamp-clients ones, see [opamp-clients](#opamp-clients)). No build on the node, and no
`docker save | k3s ctr images import` — k3s pulls the published image.

```bash
for tier in 1c-4g 2c-8g 4c-16g; do
  sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade "o11yfleet-${tier}" \
    oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
    --version 0.14.2 --namespace arc-runners \
    --values "infra/arc/values/${tier}.yaml" \
    --post-renderer /usr/local/libexec/arc-dind-mirror-post-render --wait
done
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade o11yfleet-agent-2c-8g \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --version 0.14.2 --namespace arc-runners \
  --values infra/arc/values/agent-2c-8g.yaml --wait
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
