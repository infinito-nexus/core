#!/usr/bin/env bash
set -euo pipefail

: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${UPDATE_BRANCH_PREFIX:?Missing UPDATE_BRANCH_PREFIX}"
: "${UPDATE_COMMIT_MESSAGE:?Missing UPDATE_COMMIT_MESSAGE}"
: "${UPDATE_PR_TITLE:?Missing UPDATE_PR_TITLE}"
: "${UPDATE_PR_BODY:?Missing UPDATE_PR_BODY}"

UPDATE_BASE_BRANCH="${UPDATE_BASE_BRANCH:-master}"
UPDATE_BRANCH_SUFFIX="${UPDATE_BRANCH_SUFFIX:-$(date +%Y%m%d)}"
BRANCH="${UPDATE_BRANCH_PREFIX}-${UPDATE_BRANCH_SUFFIX}"

if ! command -v gh >/dev/null 2>&1; then
	echo "ERROR: gh CLI not found." >&2
	exit 1
fi

REPO="$(git remote get-url origin | sed 's|.*github\.com[:/]||' | sed 's|\.git$||')"
OWNER="${REPO%/*}"

if [[ -n "${APP_SLUG:-}" ]]; then
	BOT_LOGIN="${APP_SLUG}[bot]"
	BOT_USER_ID="$(gh api "/users/${BOT_LOGIN}" --jq .id)"
	git config user.name "${BOT_LOGIN}"
	git config user.email "${BOT_USER_ID}+${BOT_LOGIN}@users.noreply.github.com"
else
	git config user.name "github-actions[bot]"
	git config user.email "github-actions[bot]@users.noreply.github.com"
fi
git checkout -B "${BRANCH}"

if (($# > 0)); then
	git add -- "$@"
else
	git add -A
fi

if git diff --cached --quiet; then
	echo "No staged update changes found."
	exit 0
fi

git commit -m "${UPDATE_COMMIT_MESSAGE}"

LOCAL_TREE="$(git log -1 --format=%T HEAD)"
echo "Local tree: ${LOCAL_TREE}"

mapfile -t OPEN_PRS < <(
	gh pr list \
		--repo "${REPO}" \
		--state open \
		--base "${UPDATE_BASE_BRANCH}" \
		--limit 100 \
		--json number,headRefName \
		--jq ".[] | select(.headRefName != \"${BRANCH}\") | \"\(.number)\t\(.headRefName)\""
)

DUPLICATE_PR=""
for entry in "${OPEN_PRS[@]}"; do
	[[ -z "${entry}" ]] && continue
	pr_num="${entry%%$'\t'*}"
	pr_branch="${entry##*$'\t'}"
	pr_head="$(gh pr view "${pr_num}" --repo "${REPO}" --json headRefOid --jq .headRefOid 2>/dev/null || true)"
	if [[ -z "${pr_head}" ]] || ! git fetch --quiet --depth 1 origin "${pr_head}" 2>/dev/null; then
		echo "  open PR #${pr_num} (${pr_branch}): head unfetchable; treating as non-duplicate"
		continue
	fi
	pr_tree="$(git log -1 --format=%T "${pr_head}" 2>/dev/null || true)"
	echo "  open PR #${pr_num} (${pr_branch}): tree ${pr_tree}"
	if [[ -n "${pr_tree}" && "${pr_tree}" == "${LOCAL_TREE}" ]]; then
		DUPLICATE_PR="${pr_num}"
		break
	fi
done

if [[ -n "${DUPLICATE_PR}" ]]; then
	echo "Open PR #${DUPLICATE_PR} already carries this exact tree. Skipping push and PR creation."
	exit 0
fi

git push --force origin "${BRANCH}"

PR_NUMBER="$(
	gh pr list \
		--repo "${REPO}" \
		--head "${BRANCH}" \
		--base "${UPDATE_BASE_BRANCH}" \
		--json number \
		--jq '.[0].number // empty'
)"

if [[ -n "${PR_NUMBER}" ]]; then
	echo "Updating existing PR #${PR_NUMBER} for ${BRANCH}"
	gh pr edit "${PR_NUMBER}" \
		--repo "${REPO}" \
		--title "${UPDATE_PR_TITLE}" \
		--body "${UPDATE_PR_BODY}"
else
	echo "Creating PR for ${BRANCH}"
	PR_URL="$(
		gh pr create \
			--repo "${REPO}" \
			--title "${UPDATE_PR_TITLE}" \
			--body "${UPDATE_PR_BODY}" \
			--base "${UPDATE_BASE_BRANCH}" \
			--head "${OWNER}:${BRANCH}"
	)"
	PR_NUMBER="${PR_URL##*/}"
	echo "Created PR #${PR_NUMBER}: ${PR_URL}"
fi

# Close every other open PR in the same update class as superseded. A
# PR is in the same class when its branch starts with the configured
# UPDATE_BRANCH_PREFIX, so e.g. an image-versions run only retires
# stale image-versions branches and never touches repository-refs,
# skills, or human-authored PRs.
for entry in "${OPEN_PRS[@]}"; do
	[[ -z "${entry}" ]] && continue
	pr_branch="${entry##*$'\t'}"
	[[ "${pr_branch}" == "${UPDATE_BRANCH_PREFIX}-"* ]] || continue
	pr_num="${entry%%$'\t'*}"
	echo "Closing superseded PR #${pr_num} (${pr_branch})"
	gh pr close "${pr_num}" \
		--repo "${REPO}" \
		--comment "Superseded by #${PR_NUMBER}."
done
