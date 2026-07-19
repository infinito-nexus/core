#!/usr/bin/env bash
# Print docs/contributing/tools/agents/cheatsheet.md as a readable CLI page:
# highlighted headings, indented prompt blocks, dimmed table rows.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CHEATSHEET_MD="${REPO_ROOT}/docs/contributing/tools/agents/cheatsheet.md"

if [[ ! -f "${CHEATSHEET_MD}" ]]; then
	echo "make cheat: ${CHEATSHEET_MD} not found" >&2
	exit 1
fi

if [[ -t 1 ]]; then
	C_BOLD=$'\033[1m'
	C_CYAN=$'\033[36m'
	C_GREEN=$'\033[32m'
	C_DIM=$'\033[2m'
	C_RESET=$'\033[0m'
else
	C_BOLD=""
	C_CYAN=""
	C_GREEN=""
	C_DIM=""
	C_RESET=""
fi

in_code=0
while IFS= read -r line; do
	if [[ "${line}" == '```'* ]]; then
		in_code=$((1 - in_code))
		continue
	fi
	if ((in_code)); then
		printf '    %s%s%s\n' "${C_GREEN}" "${line}" "${C_RESET}"
	elif [[ "${line}" == "# "* ]]; then
		printf '%s%s%s\n' "${C_BOLD}" "${line#\# }" "${C_RESET}"
	elif [[ "${line}" == "## "* ]]; then
		printf '\n%s%s%s\n' "${C_BOLD}${C_CYAN}" "${line#\#\# }" "${C_RESET}"
	elif [[ "${line}" == "|"* ]]; then
		printf '  %s%s%s\n' "${C_DIM}" "${line}" "${C_RESET}"
	else
		printf '%s\n' "${line}"
	fi
done <"${CHEATSHEET_MD}"
