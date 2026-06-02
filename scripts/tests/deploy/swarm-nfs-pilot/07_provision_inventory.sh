#!/usr/bin/env bash
set -euo pipefail

# nfs-server group is wired by 08_extend_inventory.py; do not add via --include.
mkdir -p /tmp/inv
python3 -m cli.administration.inventory.provision /tmp/inv \
	--host "${MGR}" \
	--include svc-docker-swarm svc-docker-swarm-manager \
	svc-storage-nfs-client \
	svc-db-mariadb web-app-mediawiki \
	--workers 2
