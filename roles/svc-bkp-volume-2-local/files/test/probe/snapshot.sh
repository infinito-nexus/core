#!/usr/bin/env bash
# Drives baudolo-snapshot, the launcher that decides per run whether baudolo
# may capture the volumes from a filesystem snapshot. The decision reads
# mountinfo, inode numbers and `btrfs subvolume list`, so it can only be
# exercised against a filesystem that really exists: this builds one on a loop
# device and puts a stub on PATH in place of the docker daemon, so the
# outcomes are asserted without touching the host's real data root.
#
# Skips rather than fails where the tooling is absent (btrfs-progs, losetup,
# no free loop device, unprivileged), because the launcher's own contract on
# such a host is to decline and let the live copy run.
#
set -euo pipefail

LAUNCHER=baudolo-snapshot
SIGNAL=baudolo-maintenance
STATE_FILE=.app-control-state
SIGNAL_DIR="$(mktemp -d)"
SIGNAL_FILE="${SIGNAL_DIR}/backup.json"
trap 'rm -rf "${SIGNAL_DIR}"' EXIT
ANNOUNCE=(--maintenance-bin "${SIGNAL}" --maintenance-file "${SIGNAL_FILE}" --maintenance-seconds 600 --stopping probe-app)

if ! command -v "${LAUNCHER}" >/dev/null; then
    echo "FAIL: ${LAUNCHER} is not on PATH; the backup unit's ExecStart would fail"
    exit 1
fi
if ! command -v "${SIGNAL}" >/dev/null; then
    echo "FAIL: ${SIGNAL} is not on PATH; the backup unit could not announce its stops"
    exit 1
fi

echo "OK: ${LAUNCHER} and ${SIGNAL} are deployed and executable"

announced() {
    "${SIGNAL}" active --file "${SIGNAL_FILE}"
}

PASSTHROUGH="$("${LAUNCHER}" --mode never --state-file "${STATE_FILE}" "${ANNOUNCE[@]}" -- /bin/echo CMD --backups-dir /b)"
if [[ "${PASSTHROUGH}" != "CMD --backups-dir /b" ]]; then
    echo "FAIL: --mode never altered the command: '${PASSTHROUGH}'"
    exit 1
fi
echo "OK: --mode never hands the command through unchanged"
if [[ "$(announced)" != '["probe-app"]' ]]; then
    echo "FAIL: a live copy announced '$(announced)' instead of the application it stops"
    exit 1
fi
echo "OK: a live copy announces the application it stops before the run"
"${SIGNAL}" clear --file "${SIGNAL_FILE}"
if [[ "$(announced)" != '[]' ]]; then
    echo "FAIL: the cleared signal still announces '$(announced)'"
    exit 1
fi
echo "OK: the cleared signal announces no application"

if [[ "$(id -u)" != "0" ]] || ! command -v mkfs.btrfs >/dev/null || ! command -v losetup >/dev/null; then
    echo "SKIP: no root or no btrfs tooling; the snapshot matrix needs both"
    exit 0
fi

WORK="$(mktemp -d)"
LOOP=""

cleanup() {
    mountpoint -q "${WORK}/mnt" && umount "${WORK}/mnt"
    [[ -n "${LOOP}" ]] && losetup -d "${LOOP}" 2>/dev/null
    rm -rf "${WORK}" "${SIGNAL_DIR}"
    return 0
}
trap cleanup EXIT

truncate -s 400M "${WORK}/img"
mkfs.btrfs -q "${WORK}/img"
mkdir -p "${WORK}/mnt" "${WORK}/bin"

if ! LOOP="$(losetup --find --show "${WORK}/img" 2>/dev/null)"; then
    echo "SKIP: no free loop device for the snapshot matrix"
    exit 0
fi
mount -t btrfs "${LOOP}" "${WORK}/mnt"

SUBJECT="${WORK}/mnt/docker"
btrfs subvolume create "${SUBJECT}" >/dev/null
mkdir -p "${SUBJECT}/volumes/probe_vol/_data"
echo "${SUBJECT}" > "${WORK}/root"

cat > "${WORK}/bin/docker" <<STUB
#!/bin/sh
case "\$1 \$2" in
  "info --format") cat "${WORK}/root" ;;
  "volume ls") echo probe_vol ;;
  "volume inspect")
    printf '{"Name":"probe_vol","Driver":"local","Options":%s,"Mountpoint":"%s/volumes/probe_vol/_data"}\n' \\
      "\${VOL_OPTIONS:-{\\}}" "\$(cat "${WORK}/root")" ;;
  *) exit 1 ;;
esac
STUB
chmod 755 "${WORK}/bin/docker"
export PATH="${WORK}/bin:${PATH}"

expect() {
    local mode="$1" want="CMD${2:+ $2}" label="$3" got
    got="$("${LAUNCHER}" --mode "${mode}" --state-file "${STATE_FILE}" "${ANNOUNCE[@]}" -- /bin/echo CMD)"
    if [[ "${got}" != "${want}" ]]; then
        echo "FAIL: mode=${mode} emitted '${got}', expected '${want}'"
        exit 1
    fi
    echo "OK: ${label}"
    local stops='["probe-app"]'
    if [[ -n "${2:-}" ]]; then
        stops='[]'
    fi
    if [[ "$(announced)" != "${stops}" ]]; then
        echo "FAIL: mode=${mode} announced '$(announced)', expected '${stops}'"
        exit 1
    fi
    echo "OK: the run announced ${stops} before baudolo started"
}

expect auto "--snapshot btrfs --snapshot-subject ${SUBJECT}" \
    "a btrfs subvolume root with one plain local volume is snapshotted"

VOL_OPTIONS='{"type":"nfs"}' expect auto "" \
    "a volume declaring its own backing store keeps the live copy"

btrfs subvolume create "${SUBJECT}/btrfs" >/dev/null
expect auto "--snapshot btrfs --snapshot-subject ${SUBJECT}" \
    "a subvolume outside the volume tree is ignored, as the storage driver carves those"
btrfs subvolume delete "${SUBJECT}/btrfs" >/dev/null

btrfs subvolume delete "${SUBJECT}/volumes/probe_vol" 2>/dev/null || rm -rf "${SUBJECT}/volumes/probe_vol"
btrfs subvolume create "${SUBJECT}/volumes/probe_vol" >/dev/null
mkdir -p "${SUBJECT}/volumes/probe_vol/_data"
expect auto "" "a subvolume inside the volume tree keeps the live copy, since a snapshot omits it"
btrfs subvolume delete "${SUBJECT}/volumes/probe_vol" >/dev/null
mkdir -p "${SUBJECT}/volumes/probe_vol/_data"

btrfs subvolume snapshot -r "${SUBJECT}" "${SUBJECT}/.baudolo-stale" >/dev/null
expect auto "--snapshot btrfs --snapshot-subject ${SUBJECT}" \
    "a snapshot left by a killed run does not block the next one"
if [[ -d "${SUBJECT}/.baudolo-stale" ]]; then
    echo "FAIL: the stale snapshot survived the reap"
    exit 1
fi
echo "OK: the leftover of the killed run was reaped"

mkdir -p "${WORK}/mnt/plain/volumes/probe_vol/_data"
echo "${WORK}/mnt/plain" > "${WORK}/root"
expect auto "" "a plain directory is not a snapshot source"
if "${LAUNCHER}" --mode btrfs --state-file "${STATE_FILE}" "${ANNOUNCE[@]}" -- /bin/echo CMD >/dev/null 2>&1; then
    echo "FAIL: a stated kind degraded silently instead of aborting the run"
    exit 1
fi
echo "OK: a stated kind aborts the run rather than copying live"

echo "SNAPSHOT PROBE COMPLETE"
