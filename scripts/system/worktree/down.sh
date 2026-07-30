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

if [ "${force}" != "true" ] && [ -n "$(git -C "${path}" status --porcelain)" ]; then
	echo "FAILURE: ${path} has uncommitted changes; commit them or pass force=true" >&2
	git -C "${path}" status --short >&2
	exit 1
fi

slot="$(worktree_slot_of "${path}")"
echo ">>> Stopping the compose stack in ${path} (slot ${slot})"
if ! make -C "${path}" compose-down; then
	echo ">>> WARNING: compose-down failed; removing the worktree anyway"
fi

echo ">>> Removing worktree ${path}"
if [ "${force}" = "true" ]; then
	git worktree remove --force "${path}"
else
	git worktree remove "${path}"
fi

echo "Slot ${slot} released."
