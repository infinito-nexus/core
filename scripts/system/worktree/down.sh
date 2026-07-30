#!/usr/bin/env bash
# shellcheck shell=bash
#
# Tear down the worktree a branch was checked out into: stop its compose
# stack, then release the checkout and free its slot. Refuses to drop a
# worktree with uncommitted changes unless force=true is passed.
#
# Use `make worktree-down` rather than calling this script directly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# shellcheck source=scripts/system/worktree/lib.sh
source "${SCRIPT_DIR}/lib.sh"

branch="${1:?branch name required}"
base="${2:-}"
force="${3:-false}"

cd "${REPO_ROOT}"

base="${base:-$(worktree_default_base)}"
path="$(worktree_path "${branch}" "${base}")"

if [ ! -d "${path}" ]; then
	echo "FAILURE: no worktree at ${path} for branch '${branch}'" >&2
	exit 1
fi

if [ "${force}" != "true" ]; then
	dirty=""
	if ! dirty="$(git -C "${path}" status --porcelain)"; then
		echo "FAILURE: cannot read the git status of ${path}; pass force=true to drop it anyway" >&2
		exit 1
	fi
	if [ -n "${dirty}" ]; then
		echo "FAILURE: ${path} has uncommitted changes; commit them or pass force=true" >&2
		git -C "${path}" status --short >&2
		exit 1
	fi
fi

slot="$(worktree_slot_of "${path}")"
meta="$(worktree_meta_dir "${path}")"
echo ">>> Stopping the compose stack in ${path} (slot ${slot})"
if ! make -C "${path}" compose-down; then
	echo ">>> WARNING: compose-down failed; removing the worktree anyway"
fi

echo ">>> Removing worktree ${path}"
remove_rc=0
if [ "${force}" = "true" ]; then
	git worktree remove --force "${path}" || remove_rc=$?
else
	git worktree remove "${path}" || remove_rc=$?
fi

if [ "${remove_rc}" -ne 0 ]; then
	if [ -e "${path}" ]; then
		echo "FAILURE: git worktree remove failed and ${path} is untouched" >&2
		exit "${remove_rc}"
	fi
	if [ -z "${meta}" ]; then
		echo "FAILURE: could not resolve the metadata dir of ${path}; run 'make worktree-prune'" >&2
		exit "${remove_rc}"
	fi
	echo ">>> git deleted the checkout but could not drop ${meta}; unregistering by hand"
	unregister_rc=0
	worktree_unregister "${meta}" || unregister_rc=$?
	case "${unregister_rc}" in
	1) worktree_report_held "${meta}" ;;
	2)
		echo "FAILURE: ${meta} still registers branch '${branch}'; clear it outside the sandbox: rm -rf ${meta}" >&2
		exit 1
		;;
	esac
fi

echo "Slot ${slot} released."
