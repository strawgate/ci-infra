#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run with sudo on docker-host' >&2; exit 1; }
# Only the new worker's kubelet and VXLAN port; do not alter Docker/libvirt rules.
if ! iptables -nL ARC-KATA-KUBELET >/dev/null 2>&1; then
  iptables -N ARC-KATA-KUBELET
  iptables -A ARC-KATA-KUBELET -i lo -j RETURN
  iptables -A ARC-KATA-KUBELET -i virbr0 -j RETURN
  iptables -A ARC-KATA-KUBELET -j DROP
fi
iptables -C INPUT -p tcp --dport 10250 -j ARC-KATA-KUBELET 2>/dev/null || \
  iptables -I INPUT 1 -p tcp --dport 10250 -j ARC-KATA-KUBELET
iptables -C INPUT ! -i virbr0 -p udp --dport 8472 \
  -m comment --comment arc-kata-private-vxlan -j DROP 2>/dev/null || \
  iptables -I INPUT 1 ! -i virbr0 -p udp --dport 8472 \
  -m comment --comment arc-kata-private-vxlan -j DROP
