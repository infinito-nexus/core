#!/usr/bin/env bash
set -euo pipefail

: "${PR_NUMBER:?Missing PR_NUMBER}"
: "${REPOSITORY:?Missing REPOSITORY}"
: "${GH_TOKEN:?Missing GH_TOKEN}"
: "${GITHUB_OUTPUT:?Missing GITHUB_OUTPUT}"

mapfile -t changed_paths < <(
	gh api --paginate -H "Accept: application/vnd.github+json" \
		"/repos/${REPOSITORY}/pulls/${PR_NUMBER}/files" |
		jq -r '.[] | .filename, (.previous_filename // empty)' |
		sed '/^$/d'
)

is_agent_path() {
	case "$1" in
	AGENTS.md | CLAUDE.md | GEMINI.md | */AGENTS.md | */CLAUDE.md | */GEMINI.md | agents/*)
		return 0
		;;
	*)
		return 1
		;;
	esac
}

is_markdown_or_rst() {
	case "$1" in
	*.md | *.rst)
		return 0
		;;
	*)
		return 1
		;;
	esac
}

scope="full"
run_ci_orchestrator="true"

if ((${#changed_paths[@]} > 0)); then
	all_agents=true
	all_documentation=true

	for path in "${changed_paths[@]}"; do
		if ! is_agent_path "${path}"; then
			all_agents=false
		fi

		if ! is_markdown_or_rst "${path}" || is_agent_path "${path}"; then
			all_documentation=false
		fi
	done

	if "${all_agents}"; then
		scope="agents"
		run_ci_orchestrator="false"
	elif "${all_documentation}"; then
		scope="documentation"
		run_ci_orchestrator="false"
	fi
fi

{
	echo "scope=${scope}"
	echo "run_ci_orchestrator=${run_ci_orchestrator}"
} >>"${GITHUB_OUTPUT}"

echo "Resolved PR scope: ${scope} (run_ci_orchestrator=${run_ci_orchestrator})"

if ((${#changed_paths[@]} > 0)); then
	echo "Changed paths:"
	printf ' - %s\n' "${changed_paths[@]}"
fi
