#!/usr/bin/env bash
set -euo pipefail

export ANSIBLE_HOST_KEY_CHECKING=False

python3 -m cli.administration.deploy.dedicated \
	/tmp/inv/devices.yml \
	--id svc-docker-swarm svc-storage-nfs-server svc-storage-nfs-client \
	svc-db-mariadb web-app-mediawiki \
	-p /tmp/inv/.password \
	--skip-build \
	--skip-cleanup \
	--skip-backup \
	-e @/tmp/swarm-nfs-extras.yml
