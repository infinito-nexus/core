#!/usr/bin/env bash
# Verify that ensure-subject-subvolume really carves a btrfs data root into a
# subvolume and carries every byte across. Never point it at the host's own
# data root: the real conversion stops docker.
set -euo pipefail

CONVERTER=baudolo-subject-subvolume
BTRFS_SUBVOLUME_INODE=256

if ! command -v "${CONVERTER}" >/dev/null; then
    echo "FAIL: ${CONVERTER} is not on PATH"
    exit 1
fi
echo "OK: ${CONVERTER} is deployed and executable"

if [[ "$(id -u)" != "0" ]] || ! command -v mkfs.btrfs >/dev/null || ! command -v losetup >/dev/null; then
    echo "SKIP: no root or no btrfs tooling; the conversion needs both"
    exit 0
fi

WORK="$(mktemp -d)"
LOOP=""

cleanup() {
    if mountpoint -q "${WORK}/mnt"; then
        umount "${WORK}/mnt"
    fi
    if [[ -n "${LOOP}" ]]; then
        losetup -d "${LOOP}" 2>/dev/null || true
    fi
    rm -rf "${WORK}"
    return 0
}
trap cleanup EXIT

truncate -s 400M "${WORK}/img"
mkfs.btrfs -q "${WORK}/img"
mkdir -p "${WORK}/mnt" "${WORK}/bin"

if ! LOOP="$(losetup --find --show "${WORK}/img" 2>/dev/null)"; then
    echo "SKIP: no free loop device for the conversion"
    exit 0
fi
mount -t btrfs "${LOOP}" "${WORK}/mnt"

ROOT="${WORK}/mnt/docker"
mkdir -p "${ROOT}/volumes/probe_vol/_data" "${ROOT}/image/overlay2"
head -c 65536 /dev/urandom > "${ROOT}/volumes/probe_vol/_data/payload.bin"
echo marker > "${ROOT}/image/overlay2/layer.txt"
ln -s payload.bin "${ROOT}/volumes/probe_vol/_data/link"
BEFORE="$(find "${ROOT}" | sort | sha256sum)"
CHECKSUM="$(sha256sum "${ROOT}/volumes/probe_vol/_data/payload.bin" | cut -d' ' -f1)"

printf '#!/bin/sh\necho %s\n' "${ROOT}" > "${WORK}/bin/docker"
printf '#!/bin/sh\nexit 0\n' > "${WORK}/bin/systemctl"
chmod 755 "${WORK}/bin/docker" "${WORK}/bin/systemctl"
export PATH="${WORK}/bin:${PATH}"

if [[ "$(stat -c %i "${ROOT}")" == "${BTRFS_SUBVOLUME_INODE}" ]]; then
    echo "FAIL: the fixture is already a subvolume, the conversion would be a no-op"
    exit 1
fi

"${CONVERTER}"

if [[ "$(stat -c %i "${ROOT}")" != "${BTRFS_SUBVOLUME_INODE}" ]]; then
    echo "FAIL: ${ROOT} is still a plain directory after the conversion"
    exit 1
fi
echo "OK: the data root is a btrfs subvolume root now"

if [[ "$(find "${ROOT}" | sort | sha256sum)" != "${BEFORE}" ]]; then
    echo "FAIL: the tree differs after the conversion"
    find "${ROOT}" | sort
    exit 1
fi
echo "OK: every path survived the conversion"

if [[ "$(sha256sum "${ROOT}/volumes/probe_vol/_data/payload.bin" | cut -d' ' -f1)" != "${CHECKSUM}" ]]; then
    echo "FAIL: the payload changed during the conversion"
    exit 1
fi
echo "OK: the payload is byte-identical"

if [[ ! -L "${ROOT}/volumes/probe_vol/_data/link" ]]; then
    echo "FAIL: the symlink was dereferenced instead of copied"
    exit 1
fi
echo "OK: the symlink stayed a symlink"

if [[ -e "${ROOT}.premigration" ]]; then
    echo "FAIL: ${ROOT}.premigration was left behind"
    exit 1
fi
echo "OK: no staging tree is left behind"

if ! btrfs subvolume snapshot -r "${ROOT}" "${ROOT}/.probe-snapshot" >/dev/null; then
    echo "FAIL: the converted root cannot be snapshotted, which was the whole point"
    exit 1
fi
btrfs subvolume delete "${ROOT}/.probe-snapshot" >/dev/null
echo "OK: the converted root can actually be snapshotted"

OUTPUT="$("${CONVERTER}")"
if [[ "${OUTPUT}" != *"already is a subvolume root"* ]]; then
    echo "FAIL: the second run did not report the root as already converted: ${OUTPUT}"
    exit 1
fi
echo "OK: a second run is a no-op"

echo "SUBVOLUME PROBE COMPLETE"
