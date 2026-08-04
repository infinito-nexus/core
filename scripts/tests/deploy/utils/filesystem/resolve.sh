#!/usr/bin/env bash
# Resolve which filesystem one distro iteration runs its docker data root on and
# hand the decision to the applying step.
#
# The draw happens once per distro rather than once per matrix entry, so a single
# entry covers several filesystems instead of locking all of its distros to the
# one kind that came up first. The pool is what this kernel serves, measured
# here; every distro image carries the userland for all three, baked by
# scripts/install/filesystem.sh. Naming kinds narrows the pool to them and makes the
# pick mandatory, so a host that cannot deliver one of them fails instead of
# quietly running on something else. The choice goes to the step summary, since
# reproducing a red run means re-stating it verbatim.
#
# Arguments:
#   $1 ALLOWED  space-separated subset of 'ext4 btrfs zfs' the draw may use;
#               empty draws from all three
#   $2 LABEL    what the pick belongs to, e.g. compose/web-app-gitea/debian
#   $3 DISTROS  distributions the pick covers, recorded with the decision
#   $4 SCOPE    runner | node; names where the pick gets applied. The kernel
#               measured here is the runner's either way, because the node
#               containers share it.
set -euo pipefail

ALLOWED="${1:-}"
LABEL="${2:?usage: resolve.sh ALLOWED LABEL DISTROS SCOPE}"
DISTROS="${3:-}"
SCOPE="${4:?usage: resolve.sh ALLOWED LABEL DISTROS SCOPE}"

KINDS="ext4 btrfs zfs"

note() {
	echo "filesystem: $*" >&2
	[ -n "${GITHUB_STEP_SUMMARY:-}" ] || return 0
	echo "- \`${LABEL}\` filesystem: $*" >>"${GITHUB_STEP_SUMMARY}"
}

kernel_serves() {
	local fs="$1"
	[ "${fs}" != zfs ] || [ ! -c /dev/zfs ] || return 0
	if [ "${fs}" != zfs ] && grep -qw "${fs}" /proc/filesystems 2>/dev/null; then
		return 0
	fi
	if ! command -v modinfo >/dev/null; then
		note "${fs} left out: not loaded and modinfo is unavailable to ask for the module"
		return 1
	fi
	modinfo "${fs}" >/dev/null 2>&1 && return 0
	note "${fs} left out: this kernel carries no module for it"
	return 1
}

# Param: $1 space-separated kinds the draw is allowed to use
candidates() {
	local kept="" fs
	for fs in $1; do
		if ! kernel_serves "${fs}"; then
			continue
		fi
		kept="${kept} ${fs}"
	done
	echo "${kept# }"
}

read -ra ALLOWED_KINDS <<<"${ALLOWED}"

for fs in "${ALLOWED_KINDS[@]}"; do
	case " ${KINDS} " in
	*" ${fs} "*) ;;
	*)
		echo "filesystem: '${fs}' is not one of ${KINDS}" >&2
		exit 2
		;;
	esac
done

if [ "${#ALLOWED_KINDS[@]}" -gt 0 ]; then
	REQUIRED=true
	POOL="$(candidates "${ALLOWED_KINDS[*]}")"
	if [ -z "${POOL}" ]; then
		note "this kernel serves none of '${ALLOWED_KINDS[*]}'; the applying step reports why"
		POOL="${ALLOWED_KINDS[*]}"
	fi
else
	REQUIRED=false
	POOL="$(candidates "${KINDS}")"
	POOL="${POOL:-ext4}"
fi

read -ra POOL_ENTRIES <<<"${POOL}"
PICKED="$(printf '%s\n' "${POOL_ENTRIES[@]}" | shuf -n1)"
ORIGIN="random out of '${POOL}' on the ${SCOPE}; re-state it to reproduce this run"

echo "filesystem for ${LABEL} on '${DISTROS}': ${PICKED} (${ORIGIN})"

if [ -n "${GITHUB_ENV:-}" ]; then
	{
		echo "INFINITO_DOCKER_FILESYSTEM=${PICKED}"
		echo "INFINITO_DOCKER_FILESYSTEM_REQUIRED=${REQUIRED}"
	} >>"${GITHUB_ENV}"
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
	echo "- \`${LABEL}\` runs its docker data root on \`${PICKED}\` (${ORIGIN})" \
		>>"${GITHUB_STEP_SUMMARY}"
fi
