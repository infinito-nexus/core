#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_context.sh"

export ANSIBLE_HOST_KEY_CHECKING=False

ids=(
	svc-docker-swarm
	svc-storage-nfs-server
	svc-storage-nfs-client
	svc-docker-registry
)
case "${DB_DEP}" in
mariadb) ids+=(svc-db-mariadb) ;;
postgres) ids+=(svc-db-postgres) ;;
esac
ids+=("${APP_ID}")

python3 -m cli.administration.deploy.dedicated \
	/tmp/inv/devices.yml \
	--id "${ids[@]}" \
	-p /tmp/inv/.password \
	--skip-build \
	--skip-cleanup \
	--skip-backup \
	-e @/tmp/swarm-nfs-extras.yml
