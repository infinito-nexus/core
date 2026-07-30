#!/usr/bin/env bash
# shellcheck shell=bash
#
# Drop the registrations of worktrees whose checkout directory is gone, so the
# branches they still claim can be checked out again.
#
# `git worktree prune` alone is not enough under the agent sandbox: it deletes
# the metadata directory as a whole, and the sandbox holds some of its files
# (config.worktree, commondir) as read-only bind mounts, so the unlink fails
# with EBUSY and the entry survives. Removing gitdir + HEAD unregisters the
# worktree without needing the pinned files gone.
#
# Use `make worktree-prune` rather than calling this script directly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# shellcheck source=scripts/system/worktree/lib.sh
source "${SCRIPT_DIR}/lib.sh"

cd "${REPO_ROOT}"

if ! git worktree prune -v 2>/dev/null; then
	echo ">>> git could not delete every stale entry; clearing the metadata by hand"
fi

meta_dir="$(git rev-parse --git-common-dir)/worktrees"
if [ ! -d "${meta_dir}" ]; then
	echo "No stale worktree registrations left."
	exit 0
fi

live_ids=()
while IFS= read -r line; do
	case "${line}" in
	"worktree "*) ;;
	*) continue ;;
	esac
	checkout="${line#worktree }"
	[ -f "${checkout}/.git" ] || continue
	live_ids+=("$(basename "$(worktree_meta_dir "${checkout}")")")
done < <(git worktree list --porcelain)

is_live() {
	local known
	for known in ${live_ids[@]+"${live_ids[@]}"}; do
		[ "${known}" = "${1}" ] && return 0
	done
	return 1
}

pruned=0
held=()
stuck=()
unverifiable=()
for entry in "${meta_dir}"/*; do
	[ -d "${entry}" ] || continue
	if is_live "$(basename "${entry}")"; then
		continue
	fi

	gitdir=""
	if [ -f "${entry}/gitdir" ]; then
		gitdir="$(cat "${entry}/gitdir")"
	fi

	if [ -n "${gitdir}" ]; then
		checkout="$(dirname "${gitdir}")"
		base="$(dirname "${checkout}")"
		if [ -e "${checkout}" ] || [ ! -d "${base}" ] || [ ! -x "${base}" ]; then
			unverifiable+=("$(basename "${entry}") -> ${checkout}")
			continue
		fi
	fi

	registered=false
	if [ -e "${entry}/gitdir" ] || [ -e "${entry}/HEAD" ]; then
		registered=true
	fi

	unregister_rc=0
	worktree_unregister "${entry}" || unregister_rc=$?
	case "${unregister_rc}" in
	1) held+=("${entry}") ;;
	2) stuck+=("${entry}") ;;
	esac

	if [ "${registered}" = true ]; then
		echo "Pruned $(basename "${entry}")"
		pruned=$((pruned + 1))
	fi
done

if [ "${pruned}" -eq 0 ] && [ "${#unverifiable[@]}" -eq 0 ]; then
	echo "No stale worktree registrations left."
fi

worktree_report_held ${held[@]+"${held[@]}"}

if [ "${#stuck[@]}" -gt 0 ]; then
	echo ">>> Still registered — gitdir/HEAD could not be removed, so these keep claiming their branch:" >&2
	printf '      %s\n' "${stuck[@]}" >&2
	echo ">>> Clear them outside the sandbox: rm -rf ${stuck[*]}" >&2
fi

if [ "${#unverifiable[@]}" -gt 0 ]; then
	echo ">>> Kept registered — their checkout is still on disk (or its parent is not"
	echo ">>> readable from here), so 'gone' cannot be established:"
	printf '      %s\n' "${unverifiable[@]}"
	echo ">>> Release them with 'make worktree-down branch=<name>' instead."
fi
