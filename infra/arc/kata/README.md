# Bare-metal Kata pilot

Keep the ARC control plane in `o11yfleet-arc`. Join the physical host as a
tainted k3s worker, so Kata starts each runner VM on physical KVM rather than
nested inside the ARC VM. Existing runner labels and routing are unchanged.

Pins: k3s `v1.36.4+k3s1` (matching the server), Kata `4.2.0`, ARC `0.14.2`.
Only Cloud Hypervisor's Rust runtime is enabled. The pilot label is
`o11yfleet-kata-4c-8g`, with one runner maximum. The worker reserves 64 of
the host's 72 logical CPUs and 288 GiB for existing workloads; it does not
create that reservation for the existing VM or Docker. Do not raise its budget
without reducing the existing VM allocation and rechecking aggregate usage.
Its static CPU manager leaves only CPUs `4-7,40-43` for the pilot; the existing
OS/interactive reservation (`0-3,36-39`) remains excluded. These pilot CPUs
can still overlap the old VM during staging: this is not a new dedicated
physical-core reservation against libvirt. Keep the one-runner cap.

## Stage without touching running CI

Run `just kata-check` (requires PyYAML), then stage this directory and the
matching release assets under `/data/gha-o11yfleet/arc-kata-stage` on
`docker-host`. Check the k3s binary against the release's SHA-256 list. Pull
the Kata chart locally and render it before staging; record its OCI digest.
Pre-pull the installer's images and archive them for import into the new
worker's containerd. None of these steps starts a worker or changes routing.
The guarded `install-worker-stopped.sh` may then run with sudo on the host:
it installs the verified binary and disabled service, puts worker storage under
`/data`, and leaves the join credential absent. It refuses existing Kubernetes
paths or an active host Kubernetes service. Do not run it on the ARC VM.

## Maintenance and qualification

1. Save the LIVE `maxRunners` values, then drain **every** scale set to zero.
   Cancel remaining GitHub runs only when authorized. Wait for `arc-runners`
   to contain no runner pods. Do not reset CPU-manager state.
2. Verify the stopped worker staged by `install-worker-stopped.sh`, its storage
   symlinks, and checksum manifest. Never overwrite another installation.
3. Transfer the server's agent join token to the host's root-owned, mode-0600
   `/etc/rancher/k3s/arc-join-token`, without printing it or putting it in Git.
   Enable/start the staged `k3s-agent` service. Joining uses the private libvirt
   bridge, not the LAN/Tailscale interfaces.
   Before starting, restrict inbound VXLAN UDP/8472 to `virbr0`; never expose
   it on the LAN/Tailscale interfaces. The kubelet binds to the bridge IP.
4. Verify `docker-host-kata` is Ready, has the isolation taint and bounded
   allocatable resources, and host SSH, existing Docker, and the VM are healthy.
   Import each staged archive with the new worker's
   `k3s ctr images import --platform linux/amd64`.
5. From the existing control plane, install the staged Kata chart in
   `kube-system` with `kata-values.yaml`. Its node selector must select only
   `docker-host-kata`. Verify `kata-clh-runtime-rs` and the worker's Kata label.
6. Generate the exact chart-shaped smoke pod with `just kata-smoke-pod` and
   apply it in `arc-runners`. Copy `smoke.js` into it and run `node smoke.js`.
   Check host `cloud-hypervisor` processes: they must run on the physical host.
   Check cross-node DNS, shared cache contents on the host, registry-mirror
   traffic, no OOM events, and pod cgroup accounting. Delete the smoke pod.
7. Only after smoke passes, install `runner-values.yaml` with ARC `0.14.2`
   and the existing DinD mirror post-renderer. Restore the saved fleet caps.
   Run real UI/collector builds on the opt-in label before changing any
   production workflow routing. Do not claim qualification from an idle runner.

Kata guest overhead is explicit: four guest vCPUs shared with the guest OS,
8 GiB workload memory plus 512 MiB guest memory. Kubernetes reserves an
additional 250m/768Mi for guest/host runtime overhead. The smoke check must
confirm pod-level limits actually reach Kata on our k3s/containerd versions.
If they do not, stop; do not route production jobs or hide it with CPU env vars.

## Rollback

Keep the original VM and pools. Drain/remove only the pilot scale set and
smoke pod, then uninstall this Kata Helm release (targets only its worker).
Stop `k3s-agent` on the physical host and delete `docker-host-kata` from the
cluster. Restore saved fleet caps. Preserve new-worker data and existing Docker
volumes; do not run a blanket k3s uninstall/killall script on this shared host.

Sources: [Kata installation](https://kata-containers.github.io/kata-containers/installation/),
[Kata sizing](https://github.com/kata-containers/kata-containers/blob/4.2.0/docs/how-to/how-to-size-sandbox-overhead-runtime-rs.md),
[k3s agent](https://docs.k3s.io/cli/agent).
