#!/usr/bin/env bash
# Lift the per-node data-root verdicts out of a deploy log into the job summary.
#
# Arguments:
#   $1 LOG  deploy log to read; a missing log is not an error
set -euo pipefail

LOG="${1:?usage: report.sh LOG}"
PATTERN='status=[a-z-]+ requested=[a-z]+ effective=[A-Za-z0-9_./-]+'

[ -f "${LOG}" ] || exit 0
[ -n "${GITHUB_STEP_SUMMARY:-}" ] || exit 0

if ! VERDICTS="$(grep -ohE "${PATTERN}" "${LOG}" | sort | uniq -c | sort -rn)"; then
	exit 0
fi
[ -n "${VERDICTS}" ] || exit 0

{
	echo "#### Docker data root, as actually used"
	echo
	echo "| Nodes | Effective | Requested | Status |"
	echo "|---:|---|---|---|"
	# shellcheck disable=SC2016
	echo "${VERDICTS}" | sed -E \
		's/^ *([0-9]+) status=([a-z-]+) requested=([a-z]+) effective=(.+)$/| \1 | `\4` | `\3` | \2 |/'
	echo
} >>"${GITHUB_STEP_SUMMARY}"
