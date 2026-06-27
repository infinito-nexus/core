#!/usr/bin/env bash
set -euo pipefail

_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
# shellcheck source=scripts/meta/env/load.sh
source "${_REPO_ROOT}/scripts/meta/env/load.sh"

: "${APP_ID:?APP_ID required}"

# Resolve the entity exactly as the deploy does (longest category-path strip via
# roles/categories.yml) so SERVICE_NAME matches the stack the deploy creates; a
# hand-rolled prefix strip diverges for svc-dns-/svc-registry-/... roles.
ENTITY="$(PYTHONPATH="${_REPO_ROOT}" "${PYTHON}" -c "from utils.roles.entity_name import get_entity_name; print(get_entity_name('${APP_ID}'))")"

STACK_NAME="${ENTITY}"
SERVICE_NAME="${STACK_NAME}_${ENTITY}"
CUSTOM_IMAGE_REPO="${ENTITY}_custom"

ROLE_DIR="${_REPO_ROOT}/roles/${APP_ID}"

DB_DEP=none
if [ -f "${ROLE_DIR}/meta/services.yml" ]; then
	if grep -qE '^mariadb:' "${ROLE_DIR}/meta/services.yml"; then
		DB_DEP=mariadb
	elif grep -qE '^postgres:' "${ROLE_DIR}/meta/services.yml"; then
		DB_DEP=postgres
	fi
fi

# Manager-pinned roles get no worker replica, so the drain-a-worker reschedule
# chaos (09-11) cannot apply to them.
DEFAULT_PLACEMENT_MANAGER=false
if [ -f "${ROLE_DIR}/meta/services.yml" ] &&
	grep -qE "default_placement:[[:space:]]*manager\b" "${ROLE_DIR}/meta/services.yml"; then
	DEFAULT_PLACEMENT_MANAGER=true
fi

# Node-level roles (drivers, swap, wireguard, nfs-client) and roles declaring
# skip: [swarm] create no `<stack>_<entity>` service, so the converge/reachable/
# chaos gates (07-11) have nothing to poll and must short-circuit.
HAS_SWARM_SERVICE="$(PYTHONPATH="${_REPO_ROOT}" "${PYTHON}" -c "
import os, yaml
try:
    from utils.roles.meta_lookup import get_role_skip
    swarm_skipped = 'swarm' in get_role_skip('${APP_ID}')
except Exception:
    swarm_skipped = False
has_image = False
svc = os.path.join('${ROLE_DIR}', 'meta', 'services.yml')
if os.path.exists(svc):
    data = yaml.safe_load(open(svc)) or {}
    if isinstance(data, dict):
        has_image = any(isinstance(v, dict) and 'image' in v for v in data.values())
has_tpl = any(os.path.exists(os.path.join('${ROLE_DIR}', 'templates', t)) for t in ('compose.yml.j2', 'service.yml.j2'))
print('false' if (swarm_skipped or not (has_image or has_tpl)) else 'true')
")"

# In-container HTTP probe port for the chaos reachability checks (09/11): most
# apps listen on :80, but some (ollama:11434) declare ports.internal.http.
PROBE_PORT="$(PYTHONPATH="${_REPO_ROOT}" "${PYTHON}" -c "
import os, yaml
port = 80
svc = os.path.join('${ROLE_DIR}', 'meta', 'services.yml')
if os.path.exists(svc):
    data = yaml.safe_load(open(svc)) or {}
    entity = data.get('${ENTITY}') if isinstance(data, dict) else None
    if isinstance(entity, dict):
        try:
            port = entity['ports']['internal']['http'] or 80
        except Exception:
            port = 80
print(port)
")"

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

export APP_ID ENTITY STACK_NAME SERVICE_NAME CUSTOM_IMAGE_REPO DB_DEP NFS_VOLUMES PRIMARY_NFS_VOLUME DEFAULT_PLACEMENT_MANAGER HAS_SWARM_SERVICE PROBE_PORT

# Exits the calling chaos step (09/10/11) with success when the role is
# manager-pinned (no worker task exists to drain).
skip_chaos_if_manager_pinned() {
	if [ "${DEFAULT_PLACEMENT_MANAGER}" = true ]; then
		echo "SKIP: ${ENTITY} declares default_placement: manager (single-node on the swarm manager) — drain-a-worker reschedule chaos does not apply"
		exit 0
	fi
}

# Exits the calling gate (07/09/10/11) with success when the role deploys no
# swarm service to converge or drain.
skip_if_no_swarm_service() {
	if [ "${HAS_SWARM_SERVICE}" != true ]; then
		echo "SKIP: ${ENTITY} (${APP_ID}) deploys no swarm service — converge/chaos gate does not apply"
		exit 0
	fi
}

if [ "${SWARM_NFS_PILOT_VERBOSE:-0}" = "1" ]; then
	echo "==> APP_ID=${APP_ID}"
	echo "    ENTITY=${ENTITY}"
	echo "    STACK_NAME=${STACK_NAME}"
	echo "    SERVICE_NAME=${SERVICE_NAME}"
	echo "    CUSTOM_IMAGE_REPO=${CUSTOM_IMAGE_REPO}"
	echo "    DB_DEP=${DB_DEP}"
	echo "    PRIMARY_NFS_VOLUME=${PRIMARY_NFS_VOLUME}"
	echo "    DEFAULT_PLACEMENT_MANAGER=${DEFAULT_PLACEMENT_MANAGER}"
	echo "    HAS_SWARM_SERVICE=${HAS_SWARM_SERVICE}"
	echo "    PROBE_PORT=${PROBE_PORT}"
fi
