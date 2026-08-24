#!/usr/bin/env bash
# Convert the docker data root into a btrfs subvolume of its own, which is what
# `btrfs subvolume snapshot` needs as a source. A data root created by mkdir is
# an ordinary directory inside the enclosing subvolume and cannot be snapshotted,
# so without this the launcher declines on every btrfs host.
#
# Stops docker. The original tree is kept until the daemon has answered on the
# converted root; every failure before that restores it and starts docker again.
set -euo pipefail

BTRFS_SUBVOLUME_INODE=256
DAEMON_TIMEOUT=120

report() { echo "ensure-subject-subvolume: $*"; }

command -v docker >/dev/null || {
	report "docker is not installed, nothing to convert"
	exit 0
} # nocheck: raw-docker - runs on a bare host to verify a btrfs layout, where the wrapper does not exist

ROOT="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)" # nocheck: raw-docker - see above
[[ -n "${ROOT}" && -d "${ROOT}" ]] || {
	report "the docker data root could not be resolved"
	exit 0
}

if [[ "$(stat -c %i "${ROOT}")" == "${BTRFS_SUBVOLUME_INODE}" ]]; then
	report "${ROOT} already is a subvolume root"
	exit 0
fi

if [[ "$(findmnt -no FSTYPE --target "${ROOT}")" != "btrfs" ]]; then
	report "${ROOT} is not on btrfs, so no subvolume can carry it"
	exit 0
fi

command -v btrfs >/dev/null || {
	report "the btrfs command is missing"
	exit 0
}

STAGING="${ROOT}.premigration"
if [[ -e "${STAGING}" ]]; then
	report "FAIL: ${STAGING} exists; an earlier conversion did not finish, resolve it by hand"
	exit 1
fi

restore_and_fail() {
	report "FAIL: $1; restoring the original tree"
	systemctl stop docker.socket 2>/dev/null || true # nocheck: shell-or-true -- the socket unit is absent on distros that ship docker without it; the docker unit below is stopped unconditionally
	systemctl stop docker
	rm -rf "${ROOT}"
	if [[ -d "${ROOT}" ]]; then
		btrfs subvolume delete "${ROOT}"
	fi
	mv "${STAGING}" "${ROOT}"
	systemctl start docker
	exit 1
}

daemon_answers() {
	local deadline=$((SECONDS + DAEMON_TIMEOUT))
	while ((SECONDS < deadline)); do
		if docker info >/dev/null 2>&1; then # nocheck: raw-docker - see above
			return 0
		fi
		sleep 2
	done
	return 1
}

report "converting ${ROOT} into a btrfs subvolume; docker stops for the copy"
systemctl stop docker.socket 2>/dev/null || true # nocheck: shell-or-true -- the socket unit is absent on distros that ship docker without it; the docker unit below is stopped unconditionally
systemctl stop docker

mv "${ROOT}" "${STAGING}"
btrfs subvolume create "${ROOT}"
cp -a --reflink=always "${STAGING}/." "${ROOT}/" ||
	restore_and_fail "the reflinked copy did not complete"

REMAINING="$(rsync -aHAXn --numeric-ids --itemize-changes "${STAGING}/" "${ROOT}/" | wc -l)"
if ((REMAINING > 0)); then
	restore_and_fail "${REMAINING} path(s) differ after the copy"
fi

systemctl start docker
daemon_answers || restore_and_fail "docker did not come up on the converted data root"

rm -rf "${STAGING}"
report "done; ${ROOT} is a btrfs subvolume root now"
