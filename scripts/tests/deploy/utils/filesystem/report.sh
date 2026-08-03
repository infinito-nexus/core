#!/usr/bin/env bash
# Lift the per-node data-root verdicts out of a deploy log into the job summary.
#
# Arguments:
#   $1 LOG  deploy log to read; a missing log is not an error
set -euo pipefail

LOG="${1:?usage: report.sh LOG}"
PATTERN='status=[a-z-]+ requested=[a-z0-9]+ effective=[A-Za-z0-9_./-]+'
REASON_PATTERN="${PATTERN} reason=[^']*"

[ -f "${LOG}" ] || exit 0
[ -n "${GITHUB_STEP_SUMMARY:-}" ] || exit 0

if ! VERDICTS="$(grep -ohE "${PATTERN}" "${LOG}" | sort | uniq -c | sort -rn)"; then
	exit 0
fi
[ -n "${VERDICTS}" ] || exit 0

REASONS="$(grep -ohE "${REASON_PATTERN}" "${LOG}" | sed -E 's/.* reason=//' | tr '|' '/' | sort -u)" ||
	REASONS=""

APPLIED="$(printf '%s\n' "${VERDICTS}" | grep -c 'status=applied')" || APPLIED=0
DECLINED="$(printf '%s\n' "${VERDICTS}" | grep -c 'status=declined')" || DECLINED=0
LOST=""
if [ "${APPLIED}" -eq 0 ] && [ "${DECLINED}" -gt 0 ]; then
	LOST="$(printf '%s\n' "${VERDICTS}" | sed -E 's/.*requested=([a-z0-9]+).*/\1/' | sort -u | paste -sd' ')"
fi

{
	echo "#### Docker data root, as actually used"
	echo
	echo "| Nodes | Effective | Requested | Status |"
	echo "|---:|---|---|---|"
	# shellcheck disable=SC2016
	echo "${VERDICTS}" | sed -E \
		's/^ *([0-9]+) status=([a-z-]+) requested=([a-z0-9]+) effective=(.+)$/| \1 | `\4` | `\3` | \2 |/'
	echo
	# shellcheck disable=SC2016
	[ -z "${LOST}" ] || printf '> [!WARNING]\n> No node applied `%s`; this job exercised none of it.\n\n' "${LOST}"
	[ -z "${REASONS}" ] || printf '%s\n\n' "$(echo "${REASONS}" | sed -E 's/^/- /')"
} >>"${GITHUB_STEP_SUMMARY}"
