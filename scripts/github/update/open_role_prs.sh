#!/usr/bin/env bash
set -euo pipefail

# Opens one update PR per top-level entry that changed under the given root
# (e.g. one PR per role under roles/), instead of a single combined PR.
# The actual dedup/push/PR logic is reused from open_pr.sh; this wrapper only
# isolates one entry's changes per call.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

ROOT="${1:?Usage: open_role_prs.sh <root-dir> (e.g. roles)}"

: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${UPDATE_BRANCH_PREFIX:?Missing UPDATE_BRANCH_PREFIX}"
: "${UPDATE_COMMIT_MESSAGE:?Missing UPDATE_COMMIT_MESSAGE}"
: "${UPDATE_PR_TITLE:?Missing UPDATE_PR_TITLE}"
: "${UPDATE_PR_BODY:?Missing UPDATE_PR_BODY}"

date_suffix="$(date +%Y%m%d)"

# A throwaway identity is enough for the scratch commit below; open_pr.sh sets
# the real bot identity for each published commit.
git config user.name >/dev/null 2>&1 || git config user.name "github-actions[bot]"
git config user.email >/dev/null 2>&1 || git config user.email "github-actions[bot]@users.noreply.github.com"

base="$(git rev-parse HEAD)"

git add -A -- "${ROOT}"
if git diff --cached --quiet; then
	echo "No ${ROOT} changes to split into per-entry PRs."
	exit 0
fi
git commit --quiet -m "scratch: ${ROOT} updates"
scratch="$(git rev-parse HEAD)"
git reset --quiet --hard "${base}"

mapfile -t entries < <(
	git diff --name-only "${base}" "${scratch}" -- "${ROOT}/" |
		sed -E "s#^${ROOT}/([^/]+)/.*#\1#;t;d" |
		sort -u
)

echo "Changed ${ROOT} entries: ${entries[*]:-(none)}"

for entry in "${entries[@]}"; do
	[[ -z "${entry}" ]] && continue
	echo "=== Opening PR for ${ROOT}/${entry} ==="

	git checkout --quiet --force --detach "${base}"
	git checkout --quiet "${scratch}" -- "${ROOT}/${entry}/"

	UPDATE_BRANCH_SUFFIX="${entry}-${date_suffix}" \
		UPDATE_DEDUPE_PREFIX="${UPDATE_BRANCH_PREFIX}-${entry}-" \
		UPDATE_COMMIT_MESSAGE="${UPDATE_COMMIT_MESSAGE} (${entry})" \
		UPDATE_PR_TITLE="${UPDATE_PR_TITLE} (${entry})" \
		UPDATE_PR_BODY="${UPDATE_PR_BODY}"$'\n\n'"Scope: \`${ROOT}/${entry}\`." \
		bash "${SCRIPT_DIR}/open_pr.sh" "${ROOT}/${entry}"
done

git checkout --quiet --force --detach "${base}" || true
