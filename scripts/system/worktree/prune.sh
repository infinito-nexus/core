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

cd "${REPO_ROOT}"

if ! git worktree prune -v; then
	echo ">>> git could not delete every stale entry; clearing the metadata by hand"
fi

meta_dir="$(git rev-parse --git-common-dir)/worktrees"
if [ ! -d "${meta_dir}" ]; then
	echo "No stale worktree registrations left."
	exit 0
fi

pruned=0
for entry in "${meta_dir}"/*; do
	[ -d "${entry}" ] || continue
	if [ -f "${entry}/gitdir" ] && [ -e "$(cat "${entry}/gitdir")" ]; then
		continue
	fi
	rm -f "${entry}/gitdir" "${entry}/HEAD"
	if rm -rf "${entry}"; then
		echo "Pruned $(basename "${entry}")"
	else
		echo "Pruned $(basename "${entry}") (sandbox-held leftovers stay in ${entry})"
	fi
	pruned=$((pruned + 1))
done

if [ "${pruned}" -eq 0 ]; then
	echo "No stale worktree registrations left."
fi
