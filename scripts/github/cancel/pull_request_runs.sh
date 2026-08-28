#!/usr/bin/env bash
set -euo pipefail

: "${PR_NUMBER:?Missing PR_NUMBER}"
: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${REPOSITORY:?Missing REPOSITORY}"
PR_HEAD_REF="${PR_HEAD_REF:-}"
PR_HEAD_SHA="${PR_HEAD_SHA:-}"
PR_HEAD_REPOSITORY="${PR_HEAD_REPOSITORY:-}"
: "${CURRENT_RUN_ID:?Missing CURRENT_RUN_ID}"
INCLUDE_PATHS="${INCLUDE_PATHS:-}"
KEEP_NEWEST_PER="${KEEP_NEWEST_PER:-}"
FORCE_CANCEL_AFTER_SECONDS="${FORCE_CANCEL_AFTER_SECONDS:-}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/github/cancel/lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_tools
validate_include_paths
validate_keep_newest_per
validate_force_cancel_after

# A fork PR's runs carry an empty `pull_requests` array, so the branch matcher
# is all that is left — and it cannot tell two pull requests apart that share a
# head repository and head branch. Rather than cancel the wrong one, drop the
# matcher for as long as the head is ambiguous.
disable_ambiguous_branch_fallback() {
	local rivals
	local -a query

	if [[ -z "${PR_HEAD_REF}" ]]; then
		return 0
	fi

	query=(-f state=open -f per_page=100)
	if [[ -n "${PR_HEAD_REPOSITORY}" ]]; then
		query+=(-f "head=${PR_HEAD_REPOSITORY%%/*}:${PR_HEAD_REF}")
	fi

	if ! rivals="$(
		gh api --paginate \
			-H "Accept: application/vnd.github+json" \
			-X GET "/repos/${REPOSITORY}/pulls" \
			"${query[@]}" |
			jq -s \
				--argjson pr_number "${PR_NUMBER}" \
				--arg head_ref "${PR_HEAD_REF}" \
				'[.[][] | select(.number != $pr_number and (.head.ref // "") == $head_ref)] | length'
	)"; then
		echo "WARNING: could not list open pull requests for the head; keeping the branch fallback" >&2
		return 0
	fi

	if [[ "${rivals}" != "0" ]]; then
		echo "Branch fallback disabled: ${rivals} other open pull request(s) share ${PR_HEAD_REPOSITORY%%/*}:${PR_HEAD_REF}"
		PR_HEAD_REF=""
	fi
}

echo "Searching active workflow runs for PR #${PR_NUMBER}"
if [[ -n "${PR_HEAD_SHA}${PR_HEAD_REF}${PR_HEAD_REPOSITORY}" ]]; then
	echo "Fallback matching enabled for head.sha=${PR_HEAD_SHA:-<empty>} head.ref=${PR_HEAD_REF:-<empty>} head.repo=${PR_HEAD_REPOSITORY:-<empty>}"
fi

disable_ambiguous_branch_fallback

runs="$(collect_runs)"

run_ids="$(
	printf '%s\n' "${runs}" | jq -s -r \
		--argjson pr_number "${PR_NUMBER}" \
		--arg current_run_id "${CURRENT_RUN_ID}" \
		--arg pr_head_ref "${PR_HEAD_REF}" \
		--arg pr_head_sha "${PR_HEAD_SHA}" \
		--arg pr_head_repository "${PR_HEAD_REPOSITORY}" \
		--arg include_paths "${INCLUDE_PATHS}" \
		--arg keep_newest "${KEEP_NEWEST_PER}" '
      def drop_newest: sort_by([(.run_started_at // .created_at), .id]) | .[:-1];
      def allowlist:
        $include_paths | split("\n") | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0));

      allowlist as $paths
      | unique_by(.id)
      | map(
          select($current_run_id == "" or (.id | tostring) != $current_run_id)
          | select($include_paths == "" or ((.path // "") | IN($paths[])))
          | select(.event == "pull_request" or .event == "pull_request_target")
          | select(
              any(.pull_requests[]?; (.number // -1) == $pr_number)
              or ($pr_head_sha != "" and (.head_sha // "") == $pr_head_sha)
              or (
                $pr_head_ref != ""
                and all(.pull_requests[]?; (.number // $pr_number) == $pr_number)
                and (.head_branch // "") == $pr_head_ref
                and (
                  $pr_head_repository == ""
                  or (.head_repository.full_name // "") == $pr_head_repository
                  or (.head_repository.full_name // "") == ""
                )
              )
            )
        )
      | (if $keep_newest == "all" then drop_newest
         elif $keep_newest == "event" then
           group_by(.event // "") | map(drop_newest) | flatten
         else . end)
      | .[].id
    '
)"

cancel_all "${run_ids}"
