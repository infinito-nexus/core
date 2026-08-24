#!/usr/bin/env bash
# Disaster-recovery drill for the swarm test cluster: proves the backup
# chain nfs (plus volume + secrets where the app's include closure places a
# manager repository) -> remote -> device through the
# DEPLOYED systemd units (the backup host runs the real
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

: "${DRILL_EXTRAS:?DRILL_EXTRAS required (matrix passes the round extras)}"
: "${DISK_FLOOR_MB:?DISK_FLOOR_MB required (matrix passes its watchdog floor)}"

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
UNIT_DUMPS="${INFINITO_RESCUE_DIAGNOSTICS_DIR:?INFINITO_RESCUE_DIAGNOSTICS_DIR is not set - source scripts/meta/env/load.sh first}"

DRILL_START_TS="$(docker exec "${MGR}" date +%Y%m%d%H%M%S)"

echo "==> [0/9] disarm the backup calendar timers for the duration of the drill"
for _node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}"; do
	docker exec "${_node}" timeout 660 sh -c \
		"systemctl stop 'svc-bkp-*.timer' 2>/dev/null; while systemctl is-active --quiet 'svc-bkp-*.service'; do sleep 5; done" # nocheck: shell-or-true -- a node without the timers installed has nothing to stop
done

echo "==> [1/9] seed markers (live NFS volume + manager secrets)"
docker exec "${NFS_SERVER}" sh -c \
	"mkdir -p '${NFS_VOL_DIR}' && printf '%s' '${DR_TOKEN}' > '${NFS_VOL_DIR}/${DR_MARKER}'"
docker exec "${MGR}" sh -c \
	"mkdir -p '${SECRETS_DIR}' && printf '%s' '${DR_TOKEN}' > '${SECRETS_DIR}/${DR_MARKER}'"

echo "==> [2/9] trigger the deployed backup units (volume + secrets on manager, nfs on the export host)"
_triggered=0
SECRETS_TRIGGERED=0
VOLUME_TRIGGERED=0
_rc=0
docker exec "${MGR}" bash "${TRIGGER_UNITS}" 'svc-bkp-volume-2-local*.service' "${UNIT_DUMPS}" || _rc=$?
[ "${_rc}" -eq 0 ] && _triggered=1
[ "${_rc}" -eq 0 ] && VOLUME_TRIGGERED=1
[ "${_rc}" -eq 1 ] && exit 1
_rc=0
docker exec "${MGR}" bash "${TRIGGER_UNITS}" 'svc-bkp-secrets-2-local*.service' "${UNIT_DUMPS}" || _rc=$?
[ "${_rc}" -eq 0 ] && SECRETS_TRIGGERED=1
[ "${_rc}" -eq 1 ] && exit 1
_rc=0
docker exec "${NFS_SERVER}" bash "${TRIGGER_UNITS}" 'svc-bkp-nfs-2-local*.service' "${UNIT_DUMPS}" || _rc=$?
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
	docker exec "${NFS_SERVER}" find "${DIR_BACKUPS}" -maxdepth 4 -type d 2>/dev/null || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
	docker exec "${MGR}" find "${DIR_BACKUPS}" -maxdepth 4 -type d 2>/dev/null || true        # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
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

echo "==> [3b/9] verify the volume unit captured a fresh, non-empty generation"
if [ "${VOLUME_TRIGGERED}" -eq 1 ]; then
	VOL_GEN_LATEST="$(docker exec "${MGR}" sh -c "ls -1 '${DIR_BACKUPS}/${MGR_MID}/${VOLUME_REPO}' 2>/dev/null | sort | tail -1")"
	if [ -z "${VOL_GEN_LATEST}" ] || [[ "${VOL_GEN_LATEST}" < "${DRILL_START_TS}" ]]; then
		echo "FAILURE: the volume unit ran but left no generation from this drill under ${DIR_BACKUPS}/${MGR_MID}/${VOLUME_REPO} (latest: '${VOL_GEN_LATEST:-none}', drill started ${DRILL_START_TS})"
		exit 1
	fi
	if ! docker exec "${MGR}" sh -c "find '${DIR_BACKUPS}/${MGR_MID}/${VOLUME_REPO}/${VOL_GEN_LATEST}' -path '*/files/*' -type f -size +0c 2>/dev/null | head -n1 | grep -q ."; then
		echo "FAILURE: generation ${VOL_GEN_LATEST} of the volume repo holds no non-empty volume file - the unit captured nothing, so the backup exclusion swallowed every volume"
		exit 1
	fi
	echo "    volume repo generation ${VOL_GEN_LATEST} is fresh and holds data"
else
	echo "    skipped: no volume unit is deployed on ${MGR}"
fi

echo "==> [4/9] pull to ${BACKUP_NODE} via the deployed remote-2-local unit (marker expected from ${SRC_HOST})"
docker exec -i "${BACKUP_NODE}" bash "${BKP_IN_NODE}/01_ssh_trust.sh" <"${BACKUP_KEY_PATH}"
if ! docker exec "${BACKUP_NODE}" bash "${TRIGGER_UNITS}" 'svc-bkp-remote-2-local*.service' "${UNIT_DUMPS}"; then
	echo "FAILURE: remote-2-local unit missing or failed on ${BACKUP_NODE} (role not deployed?)"
	exit 1
fi
if ! docker exec "${BACKUP_NODE}" test -f "${DIR_BACKUPS}/${SRC_REL}/${DR_MARKER}"; then
	echo "FAILURE: marker missing on ${BACKUP_NODE} after the unit pull (expected under ${DIR_BACKUPS}/${SRC_REL})"
	docker exec "${BACKUP_NODE}" find "${DIR_BACKUPS}" -maxdepth 4 2>/dev/null || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
	exit 1
fi
echo "    marker present on backup host after pull"

echo "==> [5/9] plug the LUKS 'USB' and sync via the deployed local-2-device unit"
PULLED_MB="$(docker exec "${BACKUP_NODE}" du -sm "${DIR_BACKUPS}" | awk '{print $1}')"
USB_SIZE_MB=$((PULLED_MB * 2 + 256))
[ "${USB_SIZE_MB}" -lt 2048 ] && USB_SIZE_MB=2048
echo "    ${PULLED_MB}M pulled; sizing the loop image to ${USB_SIZE_MB}M (2x pulled tree + headroom, floor 2G)"
docker exec "${BACKUP_NODE}" bash "${BKP_IN_NODE}/02_luks_device.sh" \
	"${USB_IMG}" "${DEV_MOUNT}" "${DEV_DEST}" "${USB_MAPPER}" "${USB_PASS}" "${USB_SIZE_MB}"
drill_device_teardown() {
	docker exec "${BACKUP_NODE}" umount "${DEV_MOUNT}" 2>/dev/null || true                # nocheck: shell-or-true -- teardown runs from any exit path; the device may never have been mounted
	docker exec "${BACKUP_NODE}" cryptsetup luksClose "${USB_MAPPER}" 2>/dev/null || true # nocheck: shell-or-true -- teardown runs from any exit path; the mapper may never have been opened
	docker exec "${BACKUP_NODE}" rm -f "${USB_IMG}" 2>/dev/null || true                   # nocheck: shell-or-true -- teardown runs from any exit path; the image may never have been created
}
if ! DEVICE_FREE_RAW="$(docker exec "${BACKUP_NODE}" df --output=avail -B1M "${DEV_MOUNT}" 2>/dev/null)"; then
	DEVICE_FREE_RAW=""
fi
DEVICE_FREE_MB="$(printf '%s\n' "${DEVICE_FREE_RAW}" | tail -n1 | tr -d ' ')"
if ! FREE_RAW="$(docker exec "${BACKUP_NODE}" df --output=avail -B1M "${DIR_BACKUPS}" 2>/dev/null)"; then
	FREE_RAW=""
fi
FREE_MB="$(printf '%s\n' "${FREE_RAW}" | tail -n1 | tr -d ' ')"
case "${DEVICE_FREE_MB}:${FREE_MB}" in
*[!0-9:]* | *::* | :* | *:)
	echo "FAILURE: cannot read free space on ${BACKUP_NODE} — df --output returned device '${DEVICE_FREE_MB}', backup root '${FREE_MB}'"
	drill_device_teardown
	exit 1
	;;
esac
if [ "${DEVICE_FREE_MB}" -lt "${PULLED_MB}" ]; then
	echo "FAILURE: the encrypted device offers ${DEVICE_FREE_MB}M usable after mkfs on a ${USB_SIZE_MB}M image; the ${PULLED_MB}M pulled tree does not fit"
	drill_device_teardown
	exit 1
fi
NEEDED_MB=$((PULLED_MB + DISK_FLOOR_MB))
if [ "${FREE_MB}" -lt "${NEEDED_MB}" ]; then
	echo "FAILURE: the sync holds the ${PULLED_MB}M pulled tree and its device copy at once (the restore root repeats that peak later), so ${NEEDED_MB}M must be free to stay above the ${DISK_FLOOR_MB}M watchdog floor; ${FREE_MB}M free on ${BACKUP_NODE}:${DIR_BACKUPS}"
	echo "    what fills the pulled tree (MB per machine/repo):"
	docker exec "${BACKUP_NODE}" sh -c "du -sm ${DIR_BACKUPS}/*/* 2>/dev/null | sort -rn" ||
		echo "    (du breakdown unavailable)"
	drill_device_teardown
	exit 1
fi
echo "    device offers ${DEVICE_FREE_MB}M, backup root has ${FREE_MB}M free, ${PULLED_MB}M to place"
if ! docker exec "${BACKUP_NODE}" bash "${TRIGGER_UNITS}" 'svc-bkp-local-2-device*.service' "${UNIT_DUMPS}"; then
	echo "FAILURE: local-2-device unit missing or failed on ${BACKUP_NODE} (role not deployed?)"
	exit 1
fi
if ! docker exec "${BACKUP_NODE}" find "${DEV_DEST}" -name "${DR_MARKER}" 2>/dev/null | grep -q .; then
	echo "FAILURE: marker missing on the encrypted USB after the unit sync (expected under ${DEV_DEST})"
	docker exec "${BACKUP_NODE}" find "${DEV_MOUNT}" -maxdepth 5 2>/dev/null || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
	exit 1
fi
echo "    marker present on encrypted USB"

echo "==> [6/9] tear the stack down completely (full disaster) before recovery"
if has_swarm_service; then
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
	"umount '${DEV_MOUNT}' 2>/dev/null || true; cryptsetup luksClose '${USB_MAPPER}' 2>/dev/null || true; rm -rf '${DIR_BACKUPS:?}' '${RESTORE_ROOT}'; mkdir -p '${RESTORE_ROOT}'" # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
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
docker exec "${NFS_SERVER}" rm -rf "${DR_RESTORE_STAGE:?}"

echo "==> [8b/9] restore NFS coherence after the backing-FS restore"
if docker exec "${NFS_SERVER}" systemctl cat nfs-ganesha.service >/dev/null 2>&1; then
	NFS_UNIT=nfs-ganesha
else
	NFS_UNIT=nfs-server
fi
docker exec "${NFS_SERVER}" timeout 240 systemctl try-restart "${NFS_UNIT}"
for _node in "${MGR}" "${WRK1}" "${WRK2}"; do
	docker exec "${_node}" timeout 180 sh -c \
		"umount -l '${DIR_VAR_LIB}' 2>/dev/null || true; mount '${DIR_VAR_LIB}'" # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
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
	VOL_OPTIONS="$(docker exec "${MGR}" docker volume inspect --format '{{json .Options}}' "${VOL_NAME}")"
	if [ "${VOL_OPTIONS}" != null ] && [ "${VOL_OPTIONS}" != '{}' ]; then
		echo "    volume recover skipped: '${VOL_NAME}' declares its own backing store ${VOL_OPTIONS}, which is unmounted while the stack is down - a restore would land on the node disk and be shadowed on redeploy; the [8/9] export restore already carried its data"
	else
		DR_VOL_STAGE="/var/tmp/dr-volume-restore"
		docker exec "${MGR}" bash -c "rm -rf '${DR_VOL_STAGE}'; mkdir -p '${DR_VOL_STAGE}'"
		docker exec "${BACKUP_NODE}" tar -C "${RESTORE_ROOT}" -cf - "${VOL_SRC_REL}" |
			docker exec -i "${MGR}" tar --numeric-owner -C "${DR_VOL_STAGE}" -xf -
		docker exec "${MGR}" sh -c \
			"PYTHONPATH='${NODE_SRC}' python3 -m cli.administration.recover volume '${DR_VOL_STAGE}/${VOL_SRC_REL}' localhost --no-safety-backup"
		echo "    volume '${VOL_NAME}' recovered from generation ${VOL_GEN} via the recover CLI"
		docker exec "${MGR}" rm -rf "${DR_VOL_STAGE:?}"
	fi
else
	VOL_PATH="$(docker exec "${MGR}" docker volume inspect --format '{{if .Options}}{{.Options.device}}{{end}}' "${PRIMARY_NFS_VOLUME}" 2>/dev/null || true)"
	if [ -z "${VOL_PATH}" ]; then
		echo "    volume recover skipped: ${MGR} exposes no backing store for '${PRIMARY_NFS_VOLUME}' - the volume object is node-local and lives wherever the task ran, and the [8/9] export restore already carried its data"
	else
		echo "    volume repo holds no marker by design; proving the volume recover CLI against the bound backing store instead"
		VOL_MOUNTPOINT="$(docker exec "${MGR}" docker volume inspect --format '{{.Mountpoint}}' "${PRIMARY_NFS_VOLUME}")"
		docker exec "${NFS_SERVER}" rm -f "${NFS_VOL_DIR}/${DR_MARKER}"
		DR_VOL_STAGE="/var/tmp/dr-volume-restore"
		docker exec "${MGR}" bash -c "rm -rf '${DR_VOL_STAGE}'; mkdir -p '${DR_VOL_STAGE}'"
		docker exec "${BACKUP_NODE}" tar -C "${RESTORE_ROOT}" -cf - "${SRC_REL}" |
			docker exec -i "${MGR}" tar --numeric-owner -C "${DR_VOL_STAGE}" -xf -
		docker exec "${MGR}" mkdir -p "${VOL_MOUNTPOINT}"
		docker exec "${MGR}" mount --bind "${VOL_PATH}" "${VOL_MOUNTPOINT}"
		_vol_rc=0
		docker exec "${MGR}" sh -c \
			"PYTHONPATH='${NODE_SRC}' python3 -m cli.administration.recover volume '${DR_VOL_STAGE}/${SRC_REL}' localhost --no-safety-backup" || _vol_rc=$?
		docker exec "${MGR}" umount "${VOL_MOUNTPOINT}" ||
			echo "WARNING: the bind mount at ${VOL_MOUNTPOINT} refused the umount and stays behind"
		docker exec "${MGR}" rm -rf "${DR_VOL_STAGE:?}"
		if [ "${_vol_rc}" -ne 0 ]; then
			echo "FAILURE: the volume recover CLI exited ${_vol_rc} restoring '${PRIMARY_NFS_VOLUME}' through its bound backing store"
			exit 1
		fi
		if ! docker exec "${NFS_SERVER}" test -f "${NFS_VOL_DIR}/${DR_MARKER}"; then
			echo "FAILURE: the volume recover CLI reported success but the marker did not reach the export on ${NFS_SERVER} (expected ${NFS_VOL_DIR}/${DR_MARKER})"
			exit 1
		fi
		echo "    volume '${PRIMARY_NFS_VOLUME}' recovered through its bound backing store; marker verified server-side"
	fi
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
		docker exec "${MGR}" rm -rf "${DR_SEC_STAGE:?}"
	else
		echo "FAILURE: secrets unit ran but no ${SECRETS_REPO} generation reached the device-recovered tree"
		exit 1
	fi
else
	echo "    secrets recover skipped: svc-bkp-secrets-2-local not installed on ${MGR}"
fi

docker exec "${BACKUP_NODE}" rm -rf "${RESTORE_ROOT:?}"
echo "==> recovery complete via the recover CLI: device -> nfs export, plus the volume and secrets legs reported above"
echo "    the matrix update pass boots the stack onto the recovered export; verify_recovered_marker.sh asserts the live marker there"
printf 'DR_TOKEN=%s\nDR_MARKER=%s\nNFS_SERVER=%s\nNFS_VOL_DIR=%s\n' \
	"${DR_TOKEN}" "${DR_MARKER}" "${NFS_SERVER}" "${NFS_VOL_DIR}" >"${DR_VERIFY_ENV}"
