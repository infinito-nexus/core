#!/usr/bin/env bash
# Pre-push gate: fail unless the upstream main branch is fully merged into HEAD.
# Fetches the remote main tip and requires every commit on it to be reachable
# from the current tip, so a branch can never be pushed while it lags main.
#
# Env overrides: INFINITO_MAIN_REMOTE (default origin), INFINITO_MAIN_BRANCH
# (default main).
set -euo pipefail

remote="${INFINITO_MAIN_REMOTE:-origin}" # nocheck: git maintainer tooling knob, not a deployment env key
branch="${INFINITO_MAIN_BRANCH:-main}"   # nocheck: git maintainer tooling knob, not a deployment env key

cd "$(git rev-parse --show-toplevel)"

echo "assert-main-merged: fetching ${remote}/${branch} ..." >&2
git fetch --quiet "$remote" "$branch"

if git merge-base --is-ancestor FETCH_HEAD HEAD; then
	echo "✅ assert-main-merged: ${remote}/${branch} is fully merged into HEAD." >&2
	exit 0
fi

behind="$(git rev-list --count HEAD..FETCH_HEAD)"
echo "❌ assert-main-merged: ${remote}/${branch} has ${behind} commit(s) not merged into HEAD." >&2
echo "   Merge upstream main first, e.g.: git pull ${remote} ${branch}" >&2
exit 1
