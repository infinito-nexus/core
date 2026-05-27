#!/usr/bin/env bash
set -euo pipefail

: "${BRANCH:?Missing BRANCH}"
: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${REPOSITORY:?Missing REPOSITORY}"

if ! command -v gh >/dev/null 2>&1; then
	echo "ERROR: gh CLI not found." >&2
	exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
	echo "ERROR: jq not found." >&2
	exit 1
fi

echo "Searching active workflow runs for deleted branch: ${BRANCH}"

cancel_runs_by_status() {
	local status="$1"
	local run_ids

	run_ids="$(
		gh api --paginate \
			-H "Accept: application/vnd.github+json" \
			"/repos/${REPOSITORY}/actions/runs?status=${status}&per_page=100" |
			jq -r --arg branch "${BRANCH}" '
        .workflow_runs[]
        | select(
            .head_branch == $branch
            or any(.pull_requests[]?; (.head.ref // "") == $branch)
          )
        | .id
      ' |
			sort -u
	)"

	if [[ -z "${run_ids}" ]]; then
		echo "No ${status} runs found for ${BRANCH}"
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
