#!/usr/bin/env bash
set -euo pipefail

: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${UPDATE_BRANCH_PREFIX:?Missing UPDATE_BRANCH_PREFIX}"
: "${UPDATE_COMMIT_MESSAGE:?Missing UPDATE_COMMIT_MESSAGE}"
: "${UPDATE_PR_TITLE:?Missing UPDATE_PR_TITLE}"
: "${UPDATE_PR_BODY:?Missing UPDATE_PR_BODY}"

UPDATE_BASE_BRANCH="${UPDATE_BASE_BRANCH:-master}"
UPDATE_BRANCH_SUFFIX="${UPDATE_BRANCH_SUFFIX:-$(date +%Y%m%d)}"
UPDATE_DEDUPE_PREFIX="${UPDATE_DEDUPE_PREFIX:-${UPDATE_BRANCH_PREFIX}-}"

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

git checkout --detach HEAD

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

fingerprint_ref() {
	local ref="$1"
	shift
	if (($# == 0)); then
		git rev-parse "${ref}^{tree}"
		return
	fi
	local path blob
	{
		for path in "$@"; do
			blob="$(git rev-parse "${ref}:${path}" 2>/dev/null || echo MISSING)"
			printf '%s\t%s\n' "${blob}" "${path}"
		done
	} | sort | git hash-object --stdin
}

mapfile -t CHANGED_FILES < <(git diff --name-only HEAD~1 HEAD)
LOCAL_FP="$(fingerprint_ref HEAD "${CHANGED_FILES[@]}")"
echo "Local fingerprint: ${LOCAL_FP} over ${#CHANGED_FILES[@]} file(s)"

mapfile -t OPEN_PRS < <(
	gh pr list \
		--repo "${REPO}" \
		--state open \
		--base "${UPDATE_BASE_BRANCH}" \
		--limit 100 \
		--json number,headRefName \
		--jq ".[] | select(.headRefName | startswith(\"${UPDATE_DEDUPE_PREFIX}\")) | \"\(.number)\t\(.headRefName)\""
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
	pr_fp="$(fingerprint_ref "${pr_head}" "${CHANGED_FILES[@]}")"
	echo "  open PR #${pr_num} (${pr_branch}): fingerprint ${pr_fp}"
	if [[ "${pr_fp}" == "${LOCAL_FP}" ]]; then
		DUPLICATE_PR="${pr_num}"
		break
	fi
done

if [[ -n "${DUPLICATE_PR}" ]]; then
	echo "Open PR #${DUPLICATE_PR} already carries this exact change. Skipping push and PR creation."
	exit 0
fi

BRANCH="${UPDATE_BRANCH_PREFIX}-${UPDATE_BRANCH_SUFFIX}-${LOCAL_FP:0:7}"
echo "Pushing change to branch ${BRANCH}"

git config --local --get-regexp '^includeif\..*\.path$' 2>/dev/null |
	awk '{print $2}' |
	sort -u |
	xargs -r truncate -c -s 0
git push --force \
	"https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git" \
	"HEAD:refs/heads/${BRANCH}"

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
