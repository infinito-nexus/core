#!/usr/bin/env bash
# Disaster-recovery drill for the swarm test cluster: proves the full
# backup chain volume + secrets + nfs -> remote -> device through the
# DEPLOYED systemd units on every host (the backup host runs the real
# svc-bkp-remote-2-local and svc-bkp-local-2-device roles; the drill only
# installs the ssh pull identity and simulates the USB plug via a LUKS
# loop mount), then tears the stack down completely and recovers the same
# data back through the recover CLI (cli.administration.recover: device ->
# local root -> nfs export, docker volume and host secrets). The matrix update
# pass then boots the stack onto the recovered export and
# verify_recovered_marker.sh asserts the live marker, so no dedicated redeploy
# runs here. Runs once, between the matrix's first and second round, against
# the already-converged round-1 stack. Per-host
# routines live next to this file and execute in-node from the repo copy
# under INFINITO_NODE_SRC_DIR (one docker exec per routine). Marker probes
# are scoped per repo (volume/nfs/secrets share DR_MARKER; an unscoped
# ${MID} glob would cross-select). Device paths (mount/target) come from
# the same extras SPOT that configures the deployed role (write_extras).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/tests/deploy/swarm/utils/topology/base.sh
. "${SCRIPT_DIR}/../../utils/topology/base.sh"
# shellcheck source=scripts/tests/deploy/swarm/utils/_context.sh
source "${SCRIPT_DIR}/../../utils/_context.sh"

: "${MGR_IP:?MGR_IP required (01_bootstrap.sh must have run)}"
: "${NFS_IP:?NFS_IP required (01_bootstrap.sh must have run)}"
: "${DRILL_EXTRAS:?DRILL_EXTRAS required (matrix passes the round extras)}"

DIR_VAR_LIB="${INFINITO_DIR_VAR_LIB:?INFINITO_DIR_VAR_LIB is not set - source scripts/meta/env/load.sh first}"
DIR_BACKUPS="${INFINITO_DIR_BACKUPS:?INFINITO_DIR_BACKUPS is not set - regenerate .env via make dotenv}"
NODE_SRC="${INFINITO_NODE_SRC_DIR:?INFINITO_NODE_SRC_DIR is not set - source scripts/meta/env/load.sh first}"
BACKUP_KEY_PATH="${INFINITO_SWARM_BACKUP_KEY:?INFINITO_SWARM_BACKUP_KEY is not set - source scripts/meta/env/load.sh first}"
BKP_IN_NODE="${NODE_SRC}/scripts/tests/deploy/swarm/routine/backup"
DR_MARKER=".dr-drill-marker"
DR_TOKEN="${SWARM_NAME}-${APP_ID}-dr-drill"
DR_VERIFY_ENV="/tmp/dr-drill-verify-${APP_ID}.env"
rm -f "${DR_VERIFY_ENV}"
SECRETS_DIR="${INFINITO_DIR_SECRETS:?INFINITO_DIR_SECRETS is not set - regenerate .env via make dotenv}"
VOLUME_REPO="backup-docker-to-local"
NFS_REPO="backup-nfs-to-local"
SECRETS_REPO="backup-secrets-to-local"
USB_IMG="/var/lib/infinito-usb.img"
USB_MAPPER="usbdrill"
USB_PASS="drillpass"
RESTORE_ROOT="/var/tmp/dr-device-restored"
DEV_MOUNT="$(python3 -c "import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))['applications']['svc-bkp-local-2-device']['services']['local-2-device']['mount'])" "${DRILL_EXTRAS}")"
DEV_TARGET="$(python3 -c "import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))['applications']['svc-bkp-local-2-device']['services']['local-2-device']['target'])" "${DRILL_EXTRAS}")"
DEV_DEST="${DEV_MOUNT}${DEV_TARGET}"

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
MARKER_PATH="$(docker exec "${NFS_SERVER}" find "${DIR_BACKUPS}/${NFS_MID}/${NFS_REPO}" -type f -name "${DR_MARKER}" -path "*/files/*/${PRIMARY_NFS_VOLUME}/${DR_MARKER}" 2>/dev/null | sort | tail -1 || true)"
if [ -n "${MARKER_PATH}" ]; then
	SRC_HOST="${NFS_SERVER}"
else
	MARKER_PATH="$(docker exec "${MGR}" find "${DIR_BACKUPS}/${MGR_MID}/${VOLUME_REPO}" -type f -name "${DR_MARKER}" -path "*/${PRIMARY_NFS_VOLUME}/files/${DR_MARKER}" 2>/dev/null | sort | tail -1 || true)"
	if [ -n "${MARKER_PATH}" ]; then
		SRC_HOST="${MGR}"
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
	_vol_marker="$(docker exec "${MGR}" find "${DIR_BACKUPS}/${MGR_MID}/${VOLUME_REPO}" -type f -name "${DR_MARKER}" -path "*/${PRIMARY_NFS_VOLUME}/files/${DR_MARKER}" 2>/dev/null | sort | tail -1 || true)"
	[ -n "${_vol_marker}" ] && VOL_MARKER_REL="${_vol_marker#"${DIR_BACKUPS}"/}"
fi

echo "==> [4/9] pull to ${BACKUP_NODE} via the deployed remote-2-local unit (providers: ${MGR_IP}, ${NFS_IP})"
docker exec -i "${BACKUP_NODE}" bash "${BKP_IN_NODE}/01_ssh_trust.sh" <"${BACKUP_KEY_PATH}"
if ! docker exec "${BACKUP_NODE}" bash "${TRIGGER_UNITS}" 'svc-bkp-remote-2-local*.service'; then
	echo "FAILURE: remote-2-local unit missing or failed on ${BACKUP_NODE} (role not deployed?)"
	exit 1
fi
if ! docker exec "${BACKUP_NODE}" test -f "${DIR_BACKUPS}/${SRC_REL}/${DR_MARKER}"; then
	echo "FAILURE: marker missing on ${BACKUP_NODE} after the unit pull (expected under ${DIR_BACKUPS}/${SRC_REL})"
	docker exec "${BACKUP_NODE}" find "${DIR_BACKUPS}" -maxdepth 4 2>/dev/null || true
	exit 1
fi
echo "    marker present on backup host after pull"

echo "==> [5/9] plug the LUKS 'USB' and sync via the deployed local-2-device unit"
USB_SIZE_MB="$(docker exec "${BACKUP_NODE}" du -sm "${DIR_BACKUPS}" | awk '{print $1}')"
USB_SIZE_MB=$((USB_SIZE_MB * 2 + 256))
[ "${USB_SIZE_MB}" -lt 2048 ] && USB_SIZE_MB=2048
echo "    sizing the loop image to ${USB_SIZE_MB}M (2x pulled tree + headroom, floor 2G)"
docker exec "${BACKUP_NODE}" bash "${BKP_IN_NODE}/02_luks_device.sh" \
	"${USB_IMG}" "${DEV_MOUNT}" "${DEV_DEST}" "${USB_MAPPER}" "${USB_PASS}" "${USB_SIZE_MB}"
if ! docker exec "${BACKUP_NODE}" bash "${TRIGGER_UNITS}" 'svc-bkp-local-2-device*.service'; then
	echo "FAILURE: local-2-device unit missing or failed on ${BACKUP_NODE} (role not deployed?)"
	exit 1
fi
if ! docker exec "${BACKUP_NODE}" find "${DEV_DEST}" -name "${DR_MARKER}" 2>/dev/null | grep -q .; then
	echo "FAILURE: marker missing on the encrypted USB after the unit sync (expected under ${DEV_DEST})"
	docker exec "${BACKUP_NODE}" find "${DEV_MOUNT}" -maxdepth 5 2>/dev/null || true
	exit 1
fi
echo "    marker present on encrypted USB"

echo "==> [6/9] tear the stack down completely (full disaster) before recovery"
if [ "${HAS_SWARM_SERVICE}" = true ]; then
	docker exec "${MGR}" bash "${BKP_IN_NODE}/04_stack_rm_wait.sh" "${STACK_NAME}"
else
	for _node in "${MGR}" "${WRK1}" "${WRK2}"; do
		docker exec "${_node}" sh -c \
			"ids=\$(docker ps -q --filter label=com.docker.compose.project=${ENTITY}); [ -z \"\$ids\" ] || docker stop \$ids"
	done
	echo "    node-local workload: stopped compose project '${ENTITY}' on every node instead of a stack rm"
fi

echo "==> [7/9] recover device -> local root via the recover CLI (full LUKS open)"
docker exec "${BACKUP_NODE}" sh -c \
	"umount '${DEV_MOUNT}' 2>/dev/null || true; cryptsetup luksClose '${USB_MAPPER}' 2>/dev/null || true; rm -rf '${DIR_BACKUPS:?}' '${RESTORE_ROOT}'; mkdir -p '${RESTORE_ROOT}'"
docker exec "${BACKUP_NODE}" sh -c \
	"printf '%s' '${USB_PASS}' | PYTHONPATH='${NODE_SRC}' python3 -m cli.administration.recover device '${USB_IMG}:${DEV_TARGET#/}:${RESTORE_ROOT}' localhost"
if ! docker exec "${BACKUP_NODE}" test -f "${RESTORE_ROOT}/${SRC_REL}/${DR_MARKER}"; then
	echo "FAILURE: marker missing after device recover (expected under ${RESTORE_ROOT}/${SRC_REL})"
	exit 1
fi
echo "    marker recovered from device into ${RESTORE_ROOT}"
docker exec "${BACKUP_NODE}" rm -f "${USB_IMG}"

echo "==> [8/9] recover local root -> live NFS export via the recover CLI"
DR_RESTORE_STAGE="/var/tmp/dr-restore-src"
docker exec "${NFS_SERVER}" bash "${BKP_IN_NODE}/05_wipe_export.sh" \
	"${NFS_VOL_DIR}" "${DR_MARKER}" "${DR_RESTORE_STAGE}"
docker exec "${BACKUP_NODE}" tar -C "${RESTORE_ROOT}/${SRC_REL}" -cf - . |
	docker exec -i "${NFS_SERVER}" tar --numeric-owner -C "${DR_RESTORE_STAGE}" -xf -
docker exec "${NFS_SERVER}" sh -c \
	"PYTHONPATH='${NODE_SRC}' python3 -m cli.administration.recover nfs '${DR_RESTORE_STAGE}:${NFS_VOL_DIR}' localhost --no-safety-backup"
if ! docker exec "${NFS_SERVER}" test -e "${NFS_VOL_DIR}/${DR_MARKER}"; then
	echo "FAILURE: marker not written back to the NFS export during recover"
	exit 1
fi
echo "    device-recovered files restored to the live NFS export"

echo "==> [8b/9] restore NFS coherence after the backing-FS restore"
docker exec "${NFS_SERVER}" timeout 120 sh -c \
	"systemctl try-restart nfs-ganesha 2>/dev/null || systemctl try-restart nfs-server"
for _node in "${MGR}" "${WRK1}" "${WRK2}"; do
	docker exec "${_node}" timeout 180 sh -c \
		"umount -l '${DIR_VAR_LIB}' 2>/dev/null || true; mount '${DIR_VAR_LIB}'"
done
for _i in $(seq 1 24); do
	if docker exec "${MGR}" sh -c \
		"touch '${DIR_VAR_LIB}/${PRIMARY_NFS_VOLUME}/.dr-coherence-probe' && rm -f '${DIR_VAR_LIB}/${PRIMARY_NFS_VOLUME}/.dr-coherence-probe'" 2>/dev/null; then
		break
	fi
	if [ "${_i}" -eq 24 ]; then
		echo "FAILURE: NFS export not writable through the client mount after the coherence restore"
		exit 1
	fi
	sleep 5
done
echo "    ganesha restarted + client mounts refreshed; export writable via ${MGR}"

echo "==> [9/9] recover docker volume + host secrets via the recover CLI"
if [ -n "${VOL_MARKER_REL}" ]; then
	VOL_SRC_REL="$(dirname "${VOL_MARKER_REL}")"
	VOL_GEN_REL="${VOL_SRC_REL%/*/files}"
	VOL_NAME_DIR="${VOL_SRC_REL%/files}"
	VOL_NAME="${VOL_NAME_DIR##*/}"
	VOL_GEN="${VOL_GEN_REL##*/}"
	DR_VOL_STAGE="/var/tmp/dr-volume-restore"
	docker exec "${MGR}" bash -c "rm -rf '${DR_VOL_STAGE}'; mkdir -p '${DR_VOL_STAGE}'"
	docker exec "${BACKUP_NODE}" tar -C "${RESTORE_ROOT}" -cf - "${VOL_SRC_REL}" |
		docker exec -i "${MGR}" tar --numeric-owner -C "${DR_VOL_STAGE}" -xf -
	docker exec "${MGR}" sh -c \
		"PYTHONPATH='${NODE_SRC}' python3 -m cli.administration.recover volume '${DR_VOL_STAGE}/${VOL_SRC_REL}' localhost --no-safety-backup"
	echo "    volume '${VOL_NAME}' recovered from generation ${VOL_GEN} via the recover CLI"
else
	echo "    volume recover skipped: the volume-2-local backup on ${MGR} did not capture the NFS-backed marker (chain already proven via the nfs repo)"
fi

if [ "${SECRETS_TRIGGERED}" -eq 1 ]; then
	SEC_FILES="$(docker exec "${BACKUP_NODE}" bash -c \
		"find '${RESTORE_ROOT}/${MGR_MID}/${SECRETS_REPO}' -type d -name files 2>/dev/null | sort | tail -1" || true)"
	if [ -n "${SEC_FILES}" ]; then
		DR_SEC_STAGE="/var/tmp/dr-secrets-restore"
		docker exec "${MGR}" bash -c "rm -rf '${DR_SEC_STAGE}'; mkdir -p '${DR_SEC_STAGE}'"
		docker exec "${BACKUP_NODE}" tar -C "${SEC_FILES}" -cf - . |
			docker exec -i "${MGR}" tar --numeric-owner -C "${DR_SEC_STAGE}" -xf -
		docker exec "${MGR}" rm -f "${SECRETS_DIR}/${DR_MARKER}"
		docker exec "${MGR}" sh -c \
			"PYTHONPATH='${NODE_SRC}' python3 -m cli.administration.recover secrets '${DR_SEC_STAGE}' localhost --no-safety-backup"
		if ! docker exec "${MGR}" test -f "${SECRETS_DIR}/${DR_MARKER}"; then
			echo "FAILURE: secrets marker not restored into ${SECRETS_DIR}"
			exit 1
		fi
		echo "    secrets restored to ${SECRETS_DIR} via the recover CLI"
	else
		echo "FAILURE: secrets unit ran but no ${SECRETS_REPO} generation reached the device-recovered tree"
		exit 1
	fi
else
	echo "    secrets recover skipped: svc-bkp-secrets-2-local not installed on ${MGR}"
fi

echo "==> recovery complete: device -> nfs export -> volume -> secrets restored via the recover CLI"
echo "    the matrix update pass boots the stack onto the recovered export; verify_recovered_marker.sh asserts the live marker there"
printf 'DR_TOKEN=%s\nDR_MARKER=%s\nNFS_SERVER=%s\nNFS_VOL_DIR=%s\n' \
	"${DR_TOKEN}" "${DR_MARKER}" "${NFS_SERVER}" "${NFS_VOL_DIR}" >"${DR_VERIFY_ENV}"
