#!/usr/bin/env bash
# Pre-push gate: fail unless the upstream main branch is fully merged into HEAD.
# Fetches the remote main tip and requires every commit on it to be reachable
# from the current tip, so a branch can never be pushed while it lags main.
#
# Env overrides: INFINITO_MAIN_REMOTE (default origin), INFINITO_MAIN_BRANCH
# (default main), INFINITO_MAIN_COMMIT (unset: check the live branch tip; set:
# fetch and check this full commit SHA of that branch instead, e.g. the base
# SHA a CI event carries).
set -euo pipefail

remote="${INFINITO_MAIN_REMOTE:-origin}" # nocheck: git maintainer tooling knob, not a deployment env key
branch="${INFINITO_MAIN_BRANCH:-main}"   # nocheck: git maintainer tooling knob, not a deployment env key

if [[ -v INFINITO_MAIN_COMMIT ]]; then
	target="${INFINITO_MAIN_COMMIT}" # nocheck: git maintainer tooling knob, not a deployment env key
	if [[ ! "$target" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]]; then
		echo "❌ assert-main-merged: INFINITO_MAIN_COMMIT must be a full commit SHA, got '${target}'." >&2
		exit 2
	fi
	label="${remote}/${branch}@${target}"
else
	target="$branch"
	label="${remote}/${branch}"
fi

cd "$(git rev-parse --show-toplevel)"

echo "assert-main-merged: fetching ${label} ..." >&2
git fetch --quiet "$remote" "$target"

if git merge-base --is-ancestor FETCH_HEAD HEAD; then
	echo "✅ assert-main-merged: ${label} is fully merged into HEAD." >&2
	exit 0
fi

behind="$(git rev-list --count HEAD..FETCH_HEAD)"
echo "❌ assert-main-merged: ${label} has ${behind} commit(s) not merged into HEAD." >&2
echo "   Merge upstream main first, e.g.: git pull ${remote} ${branch}" >&2
exit 1
