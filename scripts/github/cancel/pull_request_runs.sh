#!/usr/bin/env bash
set -euo pipefail

: "${PR_NUMBER:?Missing PR_NUMBER}"
: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${REPOSITORY:?Missing REPOSITORY}"
: "${CURRENT_RUN_ID:?Missing CURRENT_RUN_ID}"
PR_HEAD_REF="${PR_HEAD_REF:-}"
PR_HEAD_SHA="${PR_HEAD_SHA:-}"
PR_HEAD_REPOSITORY="${PR_HEAD_REPOSITORY:-}"

if ! command -v gh >/dev/null 2>&1; then
	echo "ERROR: gh CLI not found." >&2
	exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
	echo "ERROR: jq not found." >&2
	exit 1
fi

echo "Searching active workflow runs for PR #${PR_NUMBER}"
if [[ -n "${PR_HEAD_SHA}${PR_HEAD_REF}${PR_HEAD_REPOSITORY}" ]]; then
	echo "Fallback matching enabled for head.sha=${PR_HEAD_SHA:-<empty>} head.ref=${PR_HEAD_REF:-<empty>} head.repo=${PR_HEAD_REPOSITORY:-<empty>}"
fi

cancel_runs_by_status() {
	local status="$1"
	local run_ids

	run_ids="$(
		gh api --paginate \
			-H "Accept: application/vnd.github+json" \
			"/repos/${REPOSITORY}/actions/runs?status=${status}&per_page=100" |
			jq -r \
				--argjson pr_number "${PR_NUMBER}" \
				--argjson current_run_id "${CURRENT_RUN_ID}" \
				--arg pr_head_ref "${PR_HEAD_REF}" \
				--arg pr_head_sha "${PR_HEAD_SHA}" \
				--arg pr_head_repository "${PR_HEAD_REPOSITORY}" '
	          .workflow_runs[]
	          | select(.id != $current_run_id)
	          | select(.event == "pull_request" or .event == "pull_request_target")
	          | select(
	              any(.pull_requests[]?; (.number // -1) == $pr_number)
	              or ($pr_head_sha != "" and (.head_sha // "") == $pr_head_sha)
	              or (
	                $pr_head_ref != ""
	                and (.head_branch // "") == $pr_head_ref
	                and (
	                  $pr_head_repository == ""
	                  or (.head_repository.full_name // "") == $pr_head_repository
	                  or (.head_repository.full_name // "") == ""
	                )
	              )
	            )
	          | .id
	        ' |
			sort -u
	)"

	if [[ -z "${run_ids}" ]]; then
		echo "No ${status} runs found for PR #${PR_NUMBER}"
		return 0
	fi

	while read -r run_id; do
		[[ -n "${run_id}" ]] || continue
		echo "Cancelling ${status} run ${run_id}"
		if ! gh api \
			-X POST \
			-H "Accept: application/vnd.github+json" \
			"/repos/${REPOSITORY}/actions/runs/${run_id}/cancel" \
			>/dev/null; then
			echo "Run ${run_id} could not be cancelled, likely because it already completed"
		fi
	done <<<"${run_ids}"
}

cancel_runs_by_status requested
cancel_runs_by_status pending
cancel_runs_by_status waiting
cancel_runs_by_status queued
cancel_runs_by_status in_progress
