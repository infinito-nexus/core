#!/usr/bin/env bash
#
# Restart the failed jobs of every branch whose latest workflow run ended
# cancelled.
#
# Inputs via env:
#   GH_TOKEN       token carrying actions:write on REPOSITORY
#   REPOSITORY     owner/repo
#   MAX_ATTEMPTS   leave runs alone once they reached this attempt count;
#                  0 keeps reviving a run for as long as it stays in range
#   MAX_AGE_HOURS  leave runs alone whose last update is older than this

set -euo pipefail

: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${REPOSITORY:?Missing REPOSITORY}"
: "${MAX_ATTEMPTS:?Missing MAX_ATTEMPTS}"
: "${MAX_AGE_HOURS:?Missing MAX_AGE_HOURS}"

if ! command -v gh >/dev/null 2>&1; then
	echo "ERROR: gh CLI not found." >&2
	exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
	echo "ERROR: jq not found." >&2
	exit 1
fi

cutoff="$(date -u -d "${MAX_AGE_HOURS} hours ago" +%Y-%m-%dT%H:%M:%SZ)"

echo "Rerunning cancelled runs updated after ${cutoff}, below attempt ${MAX_ATTEMPTS}"

branches="$(
	gh api --paginate \
		-H "Accept: application/vnd.github+json" \
		"/repos/${REPOSITORY}/branches?per_page=100" |
		jq -r '.[].name'
)"

while read -r branch; do
	[[ -n "${branch}" ]] || continue

	run_id="$(
		gh run list \
			--repo "${REPOSITORY}" \
			--branch "${branch}" \
			--limit 1 \
			--json databaseId,conclusion,attempt,updatedAt |
			jq -r --arg cutoff "${cutoff}" --argjson max "${MAX_ATTEMPTS}" '
        .[0]
        | select(.conclusion == "cancelled")
        | select($max == 0 or .attempt < $max)
        | select(.updatedAt > $cutoff)
        | .databaseId
      '
	)"

	[[ -n "${run_id}" ]] || continue

	echo "${branch}: rerunning the failed jobs of cancelled run ${run_id}"
	if ! gh run rerun "${run_id}" --repo "${REPOSITORY}" --failed; then
		echo "${branch}: run ${run_id} could not be rerun, likely already restarted"
	fi
done <<<"${branches}"
