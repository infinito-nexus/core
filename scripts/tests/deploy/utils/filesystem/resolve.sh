#!/usr/bin/env bash
# Resolve which filesystem one deploy runs its docker data root on and hand the
# decision to the applying step.
#
# Three inputs, three roles. ALLOWED is what the run permits at all, PICK is
# what the matrix assigned this row inside that, and ENFORCED says whether a
# human named PICK. Only ENFORCED makes it binding: the matrix narrows every row
# to one kind, so reading that narrowness as a demand would turn every transient
# condition the applying step tolerates -- a loop device it could not claim, a
# pool another job still holds -- into a red row. When PICK is not served, the
# fallback stays inside ALLOWED, so a run that permitted two kinds gets the other
# one rather than a failure. A fallback is always reported. The kernel side is
# measured here; every distro image carries the userland for all three, baked by
# scripts/install/filesystem.sh. The choice goes to the step summary, since
# reproducing a red run means re-stating it verbatim.
#
# Arguments:
#   $1 ALLOWED   space-separated subset of 'ext4 btrfs zfs' the run permits;
#                empty permits all three
#   $2 LABEL     what the pick belongs to, e.g. compose/web-app-gitea/debian
#   $3 DISTROS   distributions the pick covers, recorded with the decision
#   $4 SCOPE     runner | node; names where the pick gets applied. The kernel
#                measured here is the runner's either way, because the node
#                containers share it.
#   $5 ENFORCED  'true' when a human named this row's kind, on the run or in a
#                selection token: a host that cannot deliver it then fails
#                instead of falling back.
#   $6 PICK      the kind the matrix assigned this row; empty draws from ALLOWED
set -euo pipefail

_USAGE="usage: resolve.sh ALLOWED LABEL DISTROS SCOPE ENFORCED PICK"

ALLOWED="${1:-}"
LABEL="${2:?${_USAGE}}"
DISTROS="${3:-}"
SCOPE="${4:?${_USAGE}}"
ENFORCED="${5:-false}"
PICK="${6:-}"

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
	PERMITTED="${ALLOWED_KINDS[*]}"
else
	PERMITTED="${KINDS}"
fi
POOL="$(candidates "${PERMITTED}")"

if [ "${ENFORCED}" = true ]; then
	REQUIRED=true
	POOL="${PICK:-${PERMITTED}}"
	ORIGIN="named by the run; the applying step fails rather than substituting one"
elif [ -n "${PICK}" ] && [[ " ${POOL} " == *" ${PICK} "* ]]; then
	REQUIRED=false
	POOL="${PICK}"
	ORIGIN="assigned to this row, and served by the ${SCOPE}"
elif [ -z "${PICK}" ] && [ -n "${POOL}" ]; then
	REQUIRED=false
	ORIGIN="drawn out of '${POOL}' on the ${SCOPE}; re-state it to reproduce this run"
elif [ -n "${POOL}" ]; then
	REQUIRED=false
	note "the ${SCOPE} does not serve '${PICK}', which this row was assigned; falling back inside '${PERMITTED}'"
	ORIGIN="fallback out of '${POOL}' on the ${SCOPE}; re-state it to reproduce this run"
else
	REQUIRED=true
	POOL="${PICK:-${PERMITTED}}"
	note "the ${SCOPE} serves none of '${PERMITTED}'; the applying step reports why"
	ORIGIN="nothing in '${PERMITTED}' is served by the ${SCOPE}"
fi

read -ra POOL_ENTRIES <<<"${POOL}"
PICKED="$(printf '%s\n' "${POOL_ENTRIES[@]}" | shuf -n1)"

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
