#!/usr/bin/env bash
set -euo pipefail

# Run one test against another git ref in a throwaway worktree and let the test
# prove, by its own printed module __file__, that it imported from that ref's
# tree. The worktree is removed afterwards.
# Inputs (env):
#   ref  - the git ref to check out
#   test - the test path (relative to the repo) to run inside that ref's tree

_repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=scripts/meta/env/load.sh
. "${_repo_root}/scripts/meta/env/load.sh"

cd "${_repo_root}"

ref="${ref:-}"
test="${test:-}"
if [ -z "${ref}" ] || [ -z "${test}" ]; then
	echo "test-ref: ref=<ref> and test=<path> are required." >&2
	exit 2
fi

_tmp="$(mktemp -d)"
_worktree="${_tmp}/ref"
cleanup() {
	if [ -d "${_worktree}" ]; then
		git worktree remove --force "${_worktree}"
	fi
	git worktree prune
	rm -rf "${_tmp}"
}
trap cleanup EXIT

git worktree add --detach "${_worktree}" "${ref}"
PYTHONPATH="${_worktree}" "${PYTHON}" -m pytest "${_worktree}/${test}" -q
