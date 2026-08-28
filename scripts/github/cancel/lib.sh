#!/usr/bin/env bash
# Shared by branch_runs.sh and pull_request_runs.sh. Expects REPOSITORY,
# GH_TOKEN and INCLUDE_PATHS to be set by the caller.

RUN_STATUSES=(requested pending waiting queued in_progress)

require_tools() {
	local tool

	for tool in gh jq; do
		if ! command -v "${tool}" >/dev/null 2>&1; then
			echo "ERROR: ${tool} not found." >&2
			exit 1
		fi
	done
}

# A non-empty INCLUDE_PATHS that trims to nothing would silently select no run
# at all, turning the caller into a no-op that still reports success.
validate_include_paths() {
	if [[ -z "${INCLUDE_PATHS}" ]]; then
		return 0
	fi

	if [[ -z "$(printf '%s' "${INCLUDE_PATHS}" | tr -d '[:space:]')" ]]; then
		echo "ERROR: INCLUDE_PATHS is set but lists no workflow path." >&2
		exit 1
	fi

	echo "Restricted to workflows:"
	printf '%s\n' "${INCLUDE_PATHS}" | sed '/^[[:space:]]*$/d;s/^/  /'
}

# Mirrors the key of the concurrency group being backed up: `all` for a group
# that spans every event on a ref, `event` for one whose key contains the event
# name. Grouping any finer keeps a run alive that the group would have reaped.
validate_force_cancel_after() {
	if [[ -z "${FORCE_CANCEL_AFTER_SECONDS}" ]]; then
		return 0
	fi

	if [[ ! "${FORCE_CANCEL_AFTER_SECONDS}" =~ ^[0-9]+$ ]]; then
		echo "ERROR: FORCE_CANCEL_AFTER_SECONDS must be a whole number of seconds." >&2
		exit 1
	fi
}

validate_keep_newest_per() {
	case "${KEEP_NEWEST_PER}" in
	"" | all | event) ;;
	*)
		echo "ERROR: KEEP_NEWEST_PER must be empty, 'all' or 'event'." >&2
		exit 1
		;;
	esac
}

# Assign the result with `runs="$(collect_runs)"`, never pipe this function
# directly: on the left of a pipeline bash drops its exit status, and a failed
# page would silently narrow the run set instead of aborting.
collect_runs() {
	local status
	local payload

	for status in "${RUN_STATUSES[@]}"; do
		payload="$(
			gh api --paginate \
				-H "Accept: application/vnd.github+json" \
				"/repos/${REPOSITORY}/actions/runs?status=${status}&per_page=100"
		)" || return 1
		printf '%s' "${payload}" | jq -c '.workflow_runs[]' || return 1
	done
}

cancel_run() {
	local run_id="$1"
	local response

	if response="$(
		gh api \
			-X POST \
			-H "Accept: application/vnd.github+json" \
			"/repos/${REPOSITORY}/actions/runs/${run_id}/cancel" 2>&1
	)"; then
		return 0
	fi

	if [[ "${response}" == *"HTTP 409"* ]]; then
		echo "Run ${run_id} was already completed or already cancelling"
		return 0
	fi

	if [[ "${response}" == *"Resource not accessible"* ]]; then
		CANCEL_PERMISSION_DENIED=1
	fi

	echo "ERROR: cancelling run ${run_id} failed: ${response}" >&2
	return 1
}

# A cancel request does not stop a running step. The runner asks it to end and
# a step that ignores the signal keeps going, bounded only by its own
# `timeout-minutes` -- 350 for a deploy. The concurrency group meanwhile holds
# the newer run on `pending` until the occupant is terminal, not until it is
# cancel-requested, so a superseded sweep can block the branch for hours after
# it was told to stop. `force-cancel` is GitHub's escalation for exactly that,
# and it is worth the skipped cleanup steps here: the artefacts of a run that
# has already been superseded are of no use to anyone.
force_cancel_stragglers() {
	local run_ids="$1"
	local run_id
	local state
	local stragglers=""

	if [[ -z "${FORCE_CANCEL_AFTER_SECONDS}" || -z "${run_ids}" ]]; then
		return 0
	fi

	echo "Waiting ${FORCE_CANCEL_AFTER_SECONDS}s for the cancelled runs to end"
	sleep "${FORCE_CANCEL_AFTER_SECONDS}"

	while read -r run_id; do
		[[ -n "${run_id}" ]] || continue
		state="$(
			gh api \
				-H "Accept: application/vnd.github+json" \
				"/repos/${REPOSITORY}/actions/runs/${run_id}" --jq '.status'
		)" || return 1
		if [[ "${state}" != "completed" ]]; then
			stragglers+="${run_id}"$'\n'
		fi
	done <<<"${run_ids}"

	if [[ -z "${stragglers}" ]]; then
		echo "Every cancelled run ended on its own"
		return 0
	fi

	while read -r run_id; do
		[[ -n "${run_id}" ]] || continue
		echo "Force-cancelling run ${run_id}, still running after the cancel"
		gh api \
			-X POST \
			-H "Accept: application/vnd.github+json" \
			"/repos/${REPOSITORY}/actions/runs/${run_id}/force-cancel" >/dev/null ||
			echo "WARNING: force-cancelling run ${run_id} was rejected" >&2
	done <<<"${stragglers}"
}

# One transient failure must not abandon the remaining runs: they would keep
# burning runners. Cancel everything, then report. Only a denied token is
# fatal — a rate limit or a run that vanished between listing and cancel is
# transient, and painting the cleanup red for those trains everyone to ignore
# the red. Counting rejections instead would fail a one-run sweep on a single
# transient, which is the common shape for a branch delete.
cancel_all() {
	local run_ids="$1"
	local run_id
	local failures=0
	local successes=0
	local cancelled=""

	CANCEL_PERMISSION_DENIED=0

	if [[ -z "${run_ids}" ]]; then
		echo "No superseded runs found"
		return 0
	fi

	while read -r run_id; do
		[[ -n "${run_id}" ]] || continue
		echo "Cancelling run ${run_id}"
		if cancel_run "${run_id}"; then
			successes=$((successes + 1))
			cancelled+="${run_id}"$'\n'
		else
			failures=$((failures + 1))
		fi
	done <<<"${run_ids}"

	force_cancel_stragglers "${cancelled}"

	if ((failures == 0)); then
		return 0
	fi

	if ((CANCEL_PERMISSION_DENIED)); then
		echo "ERROR: the token may not cancel runs; ${failures} of $((failures + successes)) rejected." >&2
		return 1
	fi

	echo "WARNING: ${failures} of $((failures + successes)) run(s) could not be cancelled." >&2
}
