#!/bin/bash
# Move the kubelet dir (pod emptyDirs, i.e. job workspaces) and the shared
# pnpm store onto the XFS reflink disk, bind-mounted at their old paths, so
# pnpm can clone store files into node_modules instead of copying them.
set -euo pipefail
X=/srv/arc-xfs
KL=/var/lib/kubelet
ST=/var/cache/o11yfleet/pnpm-store

findmnt -no FSTYPE "$X" | grep -qx xfs || { echo "no xfs at $X"; exit 1; }
xfs_info "$X" | grep -q reflink=1 || { echo "reflink off"; exit 1; }
if findmnt -no SOURCE "$KL" >/dev/null 2>&1; then echo "$KL already a mount"; exit 1; fi

echo "== stopping k3s and all containers"
/usr/local/bin/k3s-killall.sh >/dev/null 2>&1 || true
systemctl is-active --quiet k3s && { echo "k3s still running"; exit 1; }

echo "== copying kubelet dir and store"
mkdir -p "$X/kubelet" "$X/pnpm-store"
rsync -aHAX --numeric-ids "$KL/" "$X/kubelet/"
rsync -aHAX --numeric-ids "$ST/" "$X/pnpm-store/"
chown 1001:1001 "$X/pnpm-store"; chmod 755 "$X/pnpm-store"

echo "== swapping in bind mounts"
mv "$KL" "$KL.pre-xfs"; mkdir "$KL"
mv "$ST" "$ST.pre-xfs"; install -d -o 1001 -g 1001 -m 755 "$ST"
cat >> /etc/fstab <<FSTAB
$X/kubelet $KL none bind,x-systemd.requires-mounts-for=$X,nofail 0 0
$X/pnpm-store $ST none bind,x-systemd.requires-mounts-for=$X,nofail 0 0
FSTAB
systemctl daemon-reload
mount "$KL"; mount "$ST"
findmnt -no SOURCE,FSTYPE "$KL"; findmnt -no SOURCE,FSTYPE "$ST"

echo "== starting k3s"
systemctl start k3s
