#!/usr/bin/env bash
# Prepare the new worker on docker-host, without joining or starting Kubernetes.
set -euo pipefail

stage=/data/gha-o11yfleet/arc-kata-stage
data=/data/gha-o11yfleet/arc-kata
[[ $EUID == 0 ]] || { echo 'Run on docker-host with sudo' >&2; exit 1; }
[[ $(hostname) == docker-host && -c /dev/kvm ]]
[[ $(getconf _NPROCESSORS_ONLN) == 72 ]]
[[ $(awk '/MemTotal/ {print $2}' /proc/meminfo) -ge 314572800 ]]
ip -4 address show virbr0 | grep -q '192.168.122.1/24'

if systemctl is-active --quiet k3s || systemctl is-active --quiet k3s-agent; then
  echo 'An existing host Kubernetes service is active; refusing to replace it' >&2
  exit 1
fi
for path in /usr/local/bin/k3s /var/lib/rancher/k3s /var/lib/kubelet /etc/rancher/k3s; do
  if [[ -e $path || -L $path ]]; then
    echo "Existing $path: stop and inspect ownership before staging" >&2
    exit 1
  fi
done
[[ -s $stage/assets/k3s && -s $stage/assets/install-k3s.sh ]]
(cd "$stage/assets" && sha256sum --ignore-missing --check sha256sum-amd64.txt)
sh -n "$stage/assets/install-k3s.sh"
printf '%s  %s\n' \
  46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad \
  "$stage/assets/install-k3s.sh" | sha256sum --check -

install -d -m 0755 "$data/k3s" "$data/kubelet" /var/lib/rancher /etc/rancher/k3s
install -d -o 1001 -g 1001 -m 0755 "$data/pnpm-store"
ln -s "$data/k3s" /var/lib/rancher/k3s
ln -s "$data/kubelet" /var/lib/kubelet
install -m 0644 "$stage/worker-config.yaml" /etc/rancher/k3s/config.yaml
install -m 0755 "$stage/assets/k3s" /usr/local/bin/k3s
INSTALL_K3S_EXEC=agent INSTALL_K3S_SKIP_DOWNLOAD=true \
  INSTALL_K3S_SKIP_ENABLE=true INSTALL_K3S_SKIP_START=true \
  sh "$stage/assets/install-k3s.sh"
systemctl daemon-reload
if systemctl is-active --quiet k3s-agent || systemctl is-enabled --quiet k3s-agent; then
  echo 'Worker must remain stopped and disabled until the maintenance window' >&2
  exit 1
fi
[[ ! -e /etc/rancher/k3s/arc-join-token ]]
/usr/local/bin/k3s --version
echo 'Worker staged, stopped, disabled, and without a join credential'
