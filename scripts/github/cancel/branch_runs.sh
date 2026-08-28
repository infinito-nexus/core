#!/usr/bin/env bash
set -euo pipefail

: "${BRANCH:?Missing BRANCH}"
: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${REPOSITORY:?Missing REPOSITORY}"
CURRENT_RUN_ID="${CURRENT_RUN_ID:-}"
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

echo "Searching active workflow runs for branch: ${BRANCH}"

runs="$(collect_runs)"

run_ids="$(
	printf '%s\n' "${runs}" | jq -s -r \
		--arg branch "${BRANCH}" \
		--arg current_run_id "${CURRENT_RUN_ID}" \
		--arg include_paths "${INCLUDE_PATHS}" \
		--arg keep_newest "${KEEP_NEWEST_PER}" '
      def drop_newest: sort_by([(.run_started_at // .created_at), .id]) | .[:-1];
      def allowlist:
        $include_paths | split("\n") | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0));

      allowlist as $paths
      | unique_by(.id)
      | map(
          select(.path != ".github/workflows/entry-pr-closed-cancel-workflows.yml")
          | select($current_run_id == "" or (.id | tostring) != $current_run_id)
          | select($include_paths == "" or ((.path // "") | IN($paths[])))
          | select(
              .head_branch == $branch
              or any(.pull_requests[]?; (.head.ref // "") == $branch)
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
