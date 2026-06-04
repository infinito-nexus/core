#!/usr/bin/env bash
set -euo pipefail

ssh-keygen -t ed25519 -N "" -f /tmp/swarm-nfs-admin.key -C "swarm-test" -q
ADMIN_PUBKEY=$(cat /tmp/swarm-nfs-admin.key.pub)

RUNTIME_VALUE="$(python3 -m cli.meta.runtime)"

cat >/tmp/swarm-nfs-extras.yml <<EOF
RUNTIME: "${RUNTIME_VALUE}"
TLS_MODE: "self_signed"
networks:
  internet:
    dns: "1.1.1.1" # nocheck: hardcoded-dns-resolver
storage:
  backend: nfs
  nfs:
    server: ${NFS_IP}
    export_base: /srv/nfs
    # NFSv4 pseudo-root does not negotiate against the act kernel.
    version: 3
svc_storage_nfs_server_export_options: >-
  rw,sync,no_subtree_check,no_root_squash,no_all_squash
swarm:
  manager:
    advertise_addr: ${MGR_IP}
  network:
    encryption: true
  registry:
    host: "${MGR}"
    port: 5000
nfs_server_ip: ${NFS_IP}
users:
  administrator:
    authorized_keys:
      - "${ADMIN_PUBKEY}"
EOF
cat /tmp/swarm-nfs-extras.yml
