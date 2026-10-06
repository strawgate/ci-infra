# Bare-metal Kata runners

All eight ARC labels run as Kata microVMs on `docker-host-kata`.
The `o11yfleet-arc` VM hosts the k3s control plane and ARC controller;
runner VMs use physical KVM directly, not nested virtualization.
Existing labels, caps, images and workload budgets are preserved.

Pins: k3s `v1.36.4+k3s1`, Kata `4.2.0`, ARC `0.14.2`.
Only Cloud Hypervisor's Rust runtime (`kata-clh-runtime-rs`) is enabled.

## Resource boundaries

- Worker: 56 allocatable logical CPUs and about 190 GiB RAM.
- OS/interactive CPUs: `0-3,36-39`, excluded from runner allocations.
- Control-plane VM: eight vCPUs pinned to `8-11,44-47`, 16 GiB RAM.
- Static CPU manager allocates at **pod scope**. All containers and the VMM
  share that budget. Do not add an exclusive CPU slice to the runner.
- `sandbox_cgroup_only=true` keeps VMM/helpers in the pod's accounting.
  CPU overhead shares the workload vCPUs; RuntimeClass CPU overhead is zero
  to preserve integer CPU allocation. Memory overhead is 768 MiB:
  512 MiB guest plus 256 MiB host runtime allowance.
- Both kubelet and fallback runc use `cgroupfs` on this worker. Qualification
  found runtime-rs/systemd programmed a different physical CPU mask from the
  CPU-manager checkpoint. Verify the actual VMM `cpuset.cpus.effective`,
  not just the guest CPU count. Host Docker's driver is unchanged.

Pool caps deliberately exceed node capacity. Kubernetes admits pods whose
requests fit the shared worker and queues excess demand. These reservations
do not prevent unrelated host Docker workloads from contending with CI.

## SSD and Docker

Containerd, kubelet and pnpm cache live under
`/data/gha-o11yfleet/arc-kata` on the dedicated SSD. Kata's `block-plain`
emptyDir mode provides guest-native ext4 for workspace, Unix Docker socket,
and Docker overlay storage. The post-renderer initializes only this pod's
emptyDir roots for UID 1001, never the shared host cache.
DinD uses its normal Unix socket, a 32 GiB Docker-store ceiling and the
existing mirror at `http://192.168.122.1:5000`. The agent lane retains its
same-container Docker/vfs topology. Startup probes allow VM exec latency.

## Validate and upgrade

Run `just check` (PyYAML required). It renders every pinned scale set and
checks scheduling, storage, limits, transport and ownership.
`just kata-smoke-pod` generates a standalone pod from the actual pilot chart.
Apply it in `arc-runners`, copy `smoke.js` into its runner, and run
`node smoke.js`. It checks guest CPU/RAM, shared-cache writes, nested Docker
pulls/builds and published HTTP services. Delete the smoke pod afterwards.
For the same-container agent topology, use `just kata-agent-smoke-pod`,
wait for dockerd, then run `node smoke.js 2 --no-shared-store` inside it.

Every scale-set upgrade must use the **Kata post-renderer**, even non-DinD
pools. From a checkout on the control-plane VM with kubeconfig configured:

```bash
just deploy-runners
```

This supports Helm 3's executable renderer and Helm 4's plugin renderer.
The old `arc-dind-mirror` renderer is only for rollback, not active Kata pools.
Publishing an image alone does not update the fleet. Qualify real GitHub jobs
for each workload topology; an idle runner is not full CI qualification.

## Installation and maintenance

1. Stage verified releases under `/data/gha-o11yfleet/arc-kata-stage`.
   `install-worker-stopped.sh` refuses existing Kubernetes paths, installs
   a disabled worker and leaves its join credential absent. Do not rerun it
   on an installed host or run it on the ARC VM.
2. Save live specs/caps and domain XML. Drain every scale set to zero and
   wait for no runner pods before changing k3s, CPU-manager state, runtime
   installation or VM allocation. Cancel jobs only with authorization.
   Never reset a checkpoint under live jobs.
3. `install-join-token.py` copies the token locally via the QEMU agent to
   root-only `/etc/rancher/k3s/arc-join-token` without printing it.
   Never commit tokens, kubeconfigs or keys.
4. Install `firewall.sh`, `arc-kata-firewall.service` and the
   `k3s-agent-firewall.conf` drop-in before starting the worker. Kubelet
   TCP/10250 accepts only bridge/loopback, VXLAN UDP/8472 only `virbr0`.
   The k3s reverse tunnel requires kubelet's loopback listener.
5. Install `kata-values.yaml` with the pinned chart in `kube-system`.
   Only the tainted physical worker may match its selector.
6. Verify readiness, allocatable resources, guest budgets, actual host VMM
   CPU sets, Docker and SSH. Run smoke tests, restore caps, and qualify
   jobs in both repositories. Leave unrelated Docker stacks untouched.

## Rollback

Drain every pool and wait for no runner pods. Restore the saved non-Kata
templates and original VM CPU/memory allocation **before** restoring caps:
the small control-plane VM cannot host the old fleet.
October 4 backups: `/root/arc-kata-cutover` in the VM and
`/data/gha-o11yfleet/arc-kata-stage/vm-before-kata.xml` on the host.
Remove only the owned Kata deployment/worker if needed. Preserve worker data
and unrelated Docker volumes. Never run blanket k3s killall/uninstall scripts
on the shared physical host.

Sources: [Kata host cgroups](https://github.com/kata-containers/kata-containers/blob/4.2.0/docs/design/host-cgroups.md),
[Kata sizing](https://github.com/kata-containers/kata-containers/blob/4.2.0/docs/how-to/how-to-size-sandbox-overhead-runtime-rs.md),
[pod resource managers](https://kubernetes.io/docs/concepts/resource-management/pod-level-resource-managers/).
