#!/usr/bin/env bash
# Disaster-recovery drill for the swarm test cluster: proves the full
# backup chain volume + secrets + nfs -> remote -> device through the
# deployed systemd units and the pull script, then recovers the same data
# back through every role's recover.py (device -> local root -> nfs export,
# docker volume and host secrets) onto the live instance. Runs once,
# between the matrix's first and second round, against the already-
# converged round-1 stack. Per-host routines live next to this file and
# execute in-node from the repo copy under INFINITO_NODE_SRC_DIR (one
# docker exec per routine). Marker probes are scoped per repo (volume/nfs/
# secrets share DR_MARKER; an unscoped ${MID} glob would cross-select).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../.." && pwd)"
# shellcheck source=scripts/tests/deploy/swarm/topology/base.sh
. "${SCRIPT_DIR}/../../topology/base.sh"
# shellcheck source=scripts/tests/deploy/swarm/utils/_context.sh
source "${SCRIPT_DIR}/../../utils/_context.sh"

: "${MGR_IP:?MGR_IP required (01_bootstrap.sh must have run)}"
: "${NFS_IP:?NFS_IP required (01_bootstrap.sh must have run)}"
: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR required (matrix sets it)}"
: "${DRILL_EXTRAS:?DRILL_EXTRAS required (matrix passes the round extras)}"

DIR_BACKUPS="/var/lib/infinito/backup"
NODE_SRC="${INFINITO_NODE_SRC_DIR:?INFINITO_NODE_SRC_DIR is not set - source scripts/meta/env/load.sh first}"
BACKUP_KEY_PATH="${INFINITO_SWARM_BACKUP_KEY:?INFINITO_SWARM_BACKUP_KEY is not set - source scripts/meta/env/load.sh first}"
BKP_IN_NODE="${NODE_SRC}/scripts/tests/deploy/swarm/routine/backup"
DR_MARKER=".dr-drill-marker"
DR_TOKEN="${SWARM_NAME}-${APP_ID}-dr-drill"
SECRETS_DIR="/var/lib/infinito/secrets"
VOLUME_REPO="backup-docker-to-local"
NFS_REPO="backup-nfs-to-local"
SECRETS_REPO="backup-secrets-to-local"
USB_IMG="/var/lib/infinito-usb.img"
USB_MOUNT="/mnt/usb-drill"
USB_MAPPER="usbdrill"
USB_PASS="drillpass"
RESTORE_ROOT="/tmp/dr-device-restored"

if [ "${HAS_SWARM_SERVICE}" != true ]; then
	echo "SKIP drill: ${APP_ID} deploys no swarm service"
	exit 0
fi
if [ -z "${PRIMARY_NFS_VOLUME}" ]; then
	echo "SKIP drill: ${APP_ID} declares no NFS-flagged volume — nothing to prove a restore against"
	exit 0
fi
if ! docker inspect "${BACKUP_NODE}" >/dev/null 2>&1; then
	echo "FAILURE: backup host ${BACKUP_NODE} is not running (01_bootstrap.sh did not run?)"
	exit 1
fi
if [ ! -f "${BACKUP_KEY_PATH}" ]; then
	echo "FAILURE: backup private key ${BACKUP_KEY_PATH} missing (write_extras did not generate it)"
	exit 1
fi

NFS_VOL_DIR="${NFS_STATE_PATH}/${PRIMARY_NFS_VOLUME}"
MGR_MID="$(docker exec "${MGR}" sha256sum /etc/machine-id | cut -c1-64)"
NFS_MID="$(docker exec "${NFS_SERVER}" sha256sum /etc/machine-id | cut -c1-64)"
echo "==> DR drill for ${APP_ID} (volume '${PRIMARY_NFS_VOLUME}')"

TRIGGER_UNITS="${NODE_SRC}/scripts/tests/deploy/swarm/utils/trigger_units.sh"

echo "==> [1/9] seed markers (live NFS volume + manager secrets)"
docker exec "${NFS_SERVER}" sh -c \
	"mkdir -p '${NFS_VOL_DIR}' && printf '%s' '${DR_TOKEN}' > '${NFS_VOL_DIR}/${DR_MARKER}'"
docker exec "${MGR}" sh -c \
	"mkdir -p '${SECRETS_DIR}' && printf '%s' '${DR_TOKEN}' > '${SECRETS_DIR}/${DR_MARKER}'"

echo "==> [2/9] trigger the deployed backup units (volume + secrets on manager, nfs on the export host)"
_triggered=0
SECRETS_TRIGGERED=0
_rc=0
docker exec "${MGR}" bash "${TRIGGER_UNITS}" 'svc-bkp-volume-2-local*.service' || _rc=$?
[ "${_rc}" -eq 0 ] && _triggered=1
[ "${_rc}" -eq 1 ] && exit 1
_rc=0
docker exec "${MGR}" bash "${TRIGGER_UNITS}" 'svc-bkp-secrets-2-local*.service' || _rc=$?
[ "${_rc}" -eq 0 ] && SECRETS_TRIGGERED=1
[ "${_rc}" -eq 1 ] && exit 1
_rc=0
docker exec "${NFS_SERVER}" bash "${TRIGGER_UNITS}" 'svc-bkp-nfs-2-local*.service' || _rc=$?
[ "${_rc}" -eq 0 ] && _triggered=1
[ "${_rc}" -eq 1 ] && exit 1
if [ "${_triggered}" -eq 0 ]; then
	echo "FAILURE: no backup unit installed on ${MGR} or ${NFS_SERVER}"
	exit 1
fi

echo "==> [3/9] locate the backup generation holding the marker"
SRC_HOST=""
SRC_IP=""
MARKER_PATH="$(docker exec "${NFS_SERVER}" find "${DIR_BACKUPS}/${NFS_MID}/${NFS_REPO}" -type f -name "${DR_MARKER}" -path '*/files/*' 2>/dev/null | sort | tail -1 || true)"
if [ -n "${MARKER_PATH}" ]; then
	SRC_HOST="${NFS_SERVER}"
	SRC_IP="${NFS_IP}"
else
	MARKER_PATH="$(docker exec "${MGR}" find "${DIR_BACKUPS}/${MGR_MID}/${VOLUME_REPO}" -type f -name "${DR_MARKER}" -path '*/files/*' 2>/dev/null | sort | tail -1 || true)"
	if [ -n "${MARKER_PATH}" ]; then
		SRC_HOST="${MGR}"
		SRC_IP="${MGR_IP}"
	fi
fi
if [ -z "${MARKER_PATH}" ]; then
	echo "FAILURE: marker not captured by any backup unit (checked ${NFS_SERVER} and ${MGR})"
	docker exec "${NFS_SERVER}" find "${DIR_BACKUPS}" -maxdepth 4 -type d 2>/dev/null || true
	docker exec "${MGR}" find "${DIR_BACKUPS}" -maxdepth 4 -type d 2>/dev/null || true
	exit 1
fi
MARKER_REL="${MARKER_PATH#"${DIR_BACKUPS}"/}"
SRC_REL="$(dirname "${MARKER_REL}")"
echo "    marker captured on ${SRC_HOST} at ${MARKER_REL}"
VOL_MARKER_REL=""
if [ "${SRC_HOST}" != "${MGR}" ]; then
	_vol_marker="$(docker exec "${MGR}" find "${DIR_BACKUPS}/${MGR_MID}/${VOLUME_REPO}" -type f -name "${DR_MARKER}" -path '*/files/*' 2>/dev/null | sort | tail -1 || true)"
	[ -n "${_vol_marker}" ] && VOL_MARKER_REL="${_vol_marker#"${DIR_BACKUPS}"/}"
fi

echo "==> [4/9] pull to ${BACKUP_NODE} with the real remote-2-local script (backup@${SRC_IP})"
docker exec -i "${BACKUP_NODE}" bash "${BKP_IN_NODE}/01_pull.sh" \
	"${SRC_IP}" "${DIR_BACKUPS}" "${NODE_SRC}" "${SRC_REL}" "${DR_MARKER}" <"${BACKUP_KEY_PATH}"
if [ "${SRC_HOST}" != "${MGR}" ]; then
	docker exec -i "${BACKUP_NODE}" bash "${BKP_IN_NODE}/01_pull.sh" \
		"${MGR_IP}" "${DIR_BACKUPS}" "${NODE_SRC}" <"${BACKUP_KEY_PATH}"
fi

echo "==> [5/9] mirror to a LUKS loop 'USB' with the real local-2-device script"
docker exec "${BACKUP_NODE}" bash "${BKP_IN_NODE}/02_mirror_to_device.sh" \
	"${NODE_SRC}" "${DIR_BACKUPS}" "${USB_IMG}" "${USB_MOUNT}" "${USB_MAPPER}" "${USB_PASS}" "${DR_MARKER}"

echo "==> [6/9] recover device -> local root via svc-bkp-local-2-device recover.py (full LUKS open)"
docker exec "${BACKUP_NODE}" bash "${BKP_IN_NODE}/03_recover_device.sh" \
	"${NODE_SRC}" "${USB_IMG}" "${USB_MOUNT}" "${RESTORE_ROOT}" "${USB_MAPPER}" "${SRC_REL}" "${DR_MARKER}" "${USB_PASS}"

echo "==> [7/9] recover local root -> live NFS export via svc-bkp-nfs-2-local recover.py"
docker exec "${MGR}" bash "${BKP_IN_NODE}/04_stack_rm_wait.sh" "${STACK_NAME}"
DR_RESTORE_STAGE="/tmp/dr-restore-src"
docker exec "${NFS_SERVER}" bash "${BKP_IN_NODE}/05_wipe_export.sh" \
	"${NFS_VOL_DIR}" "${DR_MARKER}" "${DR_RESTORE_STAGE}"
docker exec "${BACKUP_NODE}" tar -C "${RESTORE_ROOT}/${SRC_REL}" -cf - . |
	docker exec -i "${NFS_SERVER}" tar -C "${DR_RESTORE_STAGE}" -xf -
docker exec "${NFS_SERVER}" bash "${BKP_IN_NODE}/06_recover_nfs.sh" \
	"${NODE_SRC}" "${DR_RESTORE_STAGE}" "${NFS_VOL_DIR}" "${DR_MARKER}"

echo "==> [8/9] recover docker volume + host secrets via their recover.py"
if [ -n "${VOL_MARKER_REL}" ]; then
	VOL_SRC_REL="$(dirname "${VOL_MARKER_REL}")"
	VOL_GEN_REL="${VOL_SRC_REL%/*/files}"
	VOL_NAME_DIR="${VOL_SRC_REL%/files}"
	VOL_NAME="${VOL_NAME_DIR##*/}"
	VOL_GEN="${VOL_GEN_REL##*/}"
	DR_VOL_STAGE="/tmp/dr-volume-restore"
	docker exec "${MGR}" bash -c "rm -rf '${DR_VOL_STAGE}'; mkdir -p '${DR_VOL_STAGE}/${MGR_MID}'"
	docker exec "${BACKUP_NODE}" tar -C "${RESTORE_ROOT}/${MGR_MID}" -cf - . |
		docker exec -i "${MGR}" tar -C "${DR_VOL_STAGE}/${MGR_MID}" -xf -
	docker exec "${MGR}" bash "${BKP_IN_NODE}/07_recover_volume.sh" \
		"${NODE_SRC}" "${DR_VOL_STAGE}/${VOL_SRC_REL}" "${VOL_NAME}"
	echo "    volume '${VOL_NAME}' recovered from generation ${VOL_GEN} via recover.py"
else
	echo "    volume recover skipped: the volume-2-local backup on ${MGR} did not capture the NFS-backed marker (chain already proven via the nfs repo)"
fi

if [ "${SECRETS_TRIGGERED}" -eq 1 ]; then
	SEC_FILES="$(docker exec "${BACKUP_NODE}" bash -c \
		"find '${RESTORE_ROOT}/${MGR_MID}/${SECRETS_REPO}' -type d -name files 2>/dev/null | sort | tail -1" || true)"
	if [ -n "${SEC_FILES}" ]; then
		DR_SEC_STAGE="/tmp/dr-secrets-restore"
		docker exec "${MGR}" bash -c "rm -rf '${DR_SEC_STAGE}'; mkdir -p '${DR_SEC_STAGE}'"
		docker exec "${BACKUP_NODE}" tar -C "${SEC_FILES}" -cf - . |
			docker exec -i "${MGR}" tar -C "${DR_SEC_STAGE}" -xf -
		docker exec "${MGR}" bash "${BKP_IN_NODE}/08_recover_secrets.sh" \
			"${NODE_SRC}" "${DR_SEC_STAGE}" "${SECRETS_DIR}" "${DR_MARKER}"
	else
		echo "FAILURE: secrets unit ran but no ${SECRETS_REPO} generation reached the device-recovered tree"
		exit 1
	fi
else
	echo "    secrets recover skipped: svc-bkp-secrets-2-local not installed on ${MGR}"
fi

echo "==> [9/9] redeploy + verify the live volume marker"
echo "    redeploying ${STACK_NAME}"
# shellcheck source=scripts/meta/env/load.sh
source "${REPO_ROOT}/scripts/meta/env/load.sh"
python3 -m cli.administration.deploy.swarm \
	"${INFINITO_INVENTORY_DIR}/devices.yml" \
	-p "${INFINITO_INVENTORY_DIR}/.password" \
	--skip-build --skip-cleanup --skip-backup \
	-e "@inventories/development/swarm.yml" \
	-e "@${DRILL_EXTRAS}" \
	-e "VARIANT_INDEX=0"
APP_ID="${APP_ID}" bash "${SCRIPT_DIR}/../03_wait_converge.sh"

if ! docker exec "${NFS_SERVER}" grep -qF "${DR_TOKEN}" "${NFS_VOL_DIR}/${DR_MARKER}" 2>/dev/null; then
	echo "FAILURE: marker missing on the live volume after recover + redeploy"
	exit 1
fi
echo "==> DR drill PASSED: backup volume+secrets+nfs->remote->device and recover device->nfs+volume+secrets verified end to end"
