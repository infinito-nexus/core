#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=scripts/meta/env/load.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)/scripts/meta/env/load.sh"

: "${APP_ID:?APP_ID required}"

ENTITY="${APP_ID#web-app-}"
ENTITY="${ENTITY#web-svc-}"
ENTITY="${ENTITY#svc-db-}"
ENTITY="${ENTITY#svc-ai-}"
ENTITY="${ENTITY#svc-opt-}"
ENTITY="${ENTITY#svc-prx-}"
ENTITY="${ENTITY#svc-bkp-}"
ENTITY="${ENTITY#svc-storage-}"
ENTITY="${ENTITY#svc-net-}"
ENTITY="${ENTITY#svc-}"

STACK_NAME="${ENTITY}"
SERVICE_NAME="${STACK_NAME}_${ENTITY}"
CUSTOM_IMAGE_REPO="${ENTITY}_custom"

ROLE_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo .)/roles/${APP_ID}"

DB_DEP=none
if [ -f "${ROLE_DIR}/meta/services.yml" ]; then
	if grep -qE '^mariadb:' "${ROLE_DIR}/meta/services.yml"; then
		DB_DEP=mariadb
	elif grep -qE '^postgres:' "${ROLE_DIR}/meta/services.yml"; then
		DB_DEP=postgres
	fi
fi

NFS_VOLUMES=""
if [ -f "${ROLE_DIR}/meta/volumes.yml" ]; then
	NFS_VOLUMES="$(python3 -c "
import sys, yaml
with open('${ROLE_DIR}/meta/volumes.yml') as f:
    data = yaml.safe_load(f) or {}
if isinstance(data, list):
    entries = [e for e in data if isinstance(e, dict)]
elif isinstance(data, dict):
    entries = [v for v in data.values() if isinstance(v, dict)]
else:
    entries = []
for v in entries:
    if v.get('nfs') is None:
        continue
    docker_name = v.get('docker_name') or v.get('name')
    if isinstance(docker_name, str):
        print(docker_name)
")"
fi

PRIMARY_NFS_VOLUME="$(printf '%s\n' "${NFS_VOLUMES}" | head -n1)"

export APP_ID ENTITY STACK_NAME SERVICE_NAME CUSTOM_IMAGE_REPO DB_DEP NFS_VOLUMES PRIMARY_NFS_VOLUME

if [ "${SWARM_NFS_PILOT_VERBOSE:-0}" = "1" ]; then
	echo "==> APP_ID=${APP_ID}"
	echo "    ENTITY=${ENTITY}"
	echo "    STACK_NAME=${STACK_NAME}"
	echo "    SERVICE_NAME=${SERVICE_NAME}"
	echo "    CUSTOM_IMAGE_REPO=${CUSTOM_IMAGE_REPO}"
	echo "    DB_DEP=${DB_DEP}"
	echo "    PRIMARY_NFS_VOLUME=${PRIMARY_NFS_VOLUME}"
fi
