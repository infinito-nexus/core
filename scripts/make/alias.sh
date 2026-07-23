#!/usr/bin/env bash
# Print agent conversation shortcuts and the operator's terminal aliases
# as one aligned, colorized listing, paged through less on a terminal.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -z "${INFINITO_ALIAS_REPOSITORY:-}" || -z "${INFINITO_SKILLS_REPOSITORY:-}" ]]; then
	# shellcheck source=/dev/null
	source <(grep -hE '^INFINITO_(ALIAS_REPOSITORY|SKILLS_REPOSITORY)=' "${REPO_ROOT}/.env" 2>/dev/null)
fi
: "${INFINITO_ALIAS_REPOSITORY:?not set; run 'make dotenv' to generate .env}"
: "${INFINITO_SKILLS_REPOSITORY:?not set; run 'make dotenv' to generate .env}"
COMMON_AGENT_SKILL="${REPO_ROOT}/.agents/skills/shortcuts/SKILL.md"

TERMINAL_ALIASES_URL="${INFINITO_ALIAS_REPOSITORY%/}/raw/main/aliases"
TERMINAL_ALIASES_CACHE="/tmp/infinito-terminal-aliases/aliases-$(printf %s "${INFINITO_ALIAS_REPOSITORY}" | sha256sum | cut -c1-12)"

if [[ -t 1 ]]; then
	IS_TTY=1
	C_BOLD=$'\033[1m'
	C_CYAN=$'\033[36m'
	C_DIM=$'\033[2m'
	C_RESET=$'\033[0m'
else
	IS_TTY=0
	C_BOLD=""
	C_CYAN=""
	C_DIM=""
	C_RESET=""
fi

make_target_desc() {
	awk -v t="$1" '
		/^# / { if (d == "") d = substr($0, 3); next }
		$0 ~ "^"t":" { print d; exit }
		{ d = "" }
	' "${REPO_ROOT}/Makefile"
}

print_alias_file() {
	local file="$1"
	local use_make_desc="${2:-0}"
	while IFS= read -r line; do
		if [[ "${line}" =~ ^alias[[:space:]]+([^=[:space:]]+)=(.*)$ ]]; then
			local name="${BASH_REMATCH[1]}"
			local rest="${BASH_REMATCH[2]}"
			local cmd="${rest}"
			local desc=""
			if [[ "${rest}" =~ ^(.*[\'\"])[[:space:]]*\#[[:space:]]*(.*[^[:space:]])[[:space:]]*$ ]]; then
				cmd="${BASH_REMATCH[1]}"
				desc="${BASH_REMATCH[2]}"
			fi
			cmd="${cmd#[\'\"]}"
			cmd="${cmd%[\'\"]}"
			if ((use_make_desc)) && [[ -z "${desc}" ]] && [[ "${cmd}" =~ (^|[[:space:]\;\&\(])(m|make)[[:space:]]+([a-z][a-z0-9-]*) ]]; then
				desc="$(make_target_desc "${BASH_REMATCH[3]}")"
			fi
			if ((${#cmd} > 20)); then
				cmd="${cmd:0:17}..."
			fi
			if ((${#desc} > 50)); then
				desc="${desc:0:47}..."
			fi
			printf '  %s%-10s%s %s%-20s%s  %s\n' \
				"${C_CYAN}" "${name}" "${C_RESET}" \
				"${C_DIM}" "${cmd}" "${C_RESET}" "${desc}"
		fi
	done < <(sort "${file}")
}

section() {
	printf '%s%s%s\n%s%s%s\n%sMore: %s%s\n\n' \
		"${C_BOLD}" "$1" "${C_RESET}" \
		"${C_DIM}" "$2" "${C_RESET}" \
		"${C_DIM}" "$3" "${C_RESET}"
}

print_md_table() {
	while IFS= read -r line; do
		if [[ "${line}" =~ ^\|[[:space:]]*\`([^\`]+)\`[[:space:]]*\|[[:space:]]*(.*[^[:space:]])[[:space:]]*\|$ ]]; then
			printf '  %s%-10s%s %s\n' "${C_CYAN}" "${BASH_REMATCH[1]}" "${C_RESET}" "${BASH_REMATCH[2]}"
		fi
	done <"$1"
}

render() {
	section "Common Agent Aliases" \
		"Portable conversation shortcuts from the shortcuts skill; set up with: make install-skills." \
		"${INFINITO_SKILLS_REPOSITORY}"
	if [[ -s "${COMMON_AGENT_SKILL}" ]]; then
		print_md_table "${COMMON_AGENT_SKILL}"
	else
		printf '  %s(not installed: run make install-skills)%s\n' "${C_DIM}" "${C_RESET}"
	fi

	printf '\n'
	section "Infinito Terminal Aliases" \
		"Infinito.Nexus-specific shell aliases (make targets + CLI); set up with: make install-alias." \
		"docs/contributing/tools/shell/alias.md"
	if [[ -s "${REPO_ROOT}/aliases" ]]; then
		print_alias_file "${REPO_ROOT}/aliases" 1
	else
		printf '  %s(no aliases file at %s)%s\n' "${C_DIM}" "${REPO_ROOT}/aliases" "${C_RESET}"
	fi

	printf '\n'
	section "Common Terminal Aliases" \
		"General shell aliases shared across projects; set up with: make install-alias." \
		"${INFINITO_ALIAS_REPOSITORY}"
	if [[ ! -f "${TERMINAL_ALIASES_CACHE}" ]]; then
		mkdir -p "$(dirname "${TERMINAL_ALIASES_CACHE}")"
		curl -fsSL --max-time 15 "${TERMINAL_ALIASES_URL}" -o "${TERMINAL_ALIASES_CACHE}" 2>/dev/null || true
	fi
	if [[ -s "${TERMINAL_ALIASES_CACHE}" ]]; then
		print_alias_file "${TERMINAL_ALIASES_CACHE}"
	else
		printf '  %s(not available: download failed and no cache at %s)%s\n' \
			"${C_DIM}" "${TERMINAL_ALIASES_CACHE}" "${C_RESET}"
	fi
}

if ((IS_TTY)); then
	render | less -RFX
else
	render
fi
