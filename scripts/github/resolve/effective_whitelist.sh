#!/usr/bin/env bash
#
# Resolve the effective INFINITO_WHITELIST that the discover step should pass to
# scripts/github/resolve/output_apps.sh, and write it to GITHUB_OUTPUT.
#
# Inputs via env:
#   INPUT_WHITELIST  caller-provided whitelist (space-separated).
#                    Three cases, in this order of precedence:
#                      * "__ALL__" (sentinel, case-insensitive): force
#                        full deploy across the workflow's scope. Skips
#                        the diff logic and emits an empty whitelist.
#                      * any other non-empty value: used verbatim.
#                      * empty: trigger the diff-based derivation.
#
# Output (GITHUB_OUTPUT):
#   whitelist=<value>  effective whitelist. An empty string means
#                      "no restriction; deploy everything in scope".
#
# Diff logic (only when INPUT_WHITELIST is empty):
#   1. Run scripts/meta/resolve/diff/affected_roles.sh.
#   2. If it returns "__ALL__", emit empty whitelist.
#   3. Otherwise emit the resolved (transitively expanded) role list.

set -euo pipefail

: "${GITHUB_OUTPUT:?Missing GITHUB_OUTPUT}"

input="${INPUT_WHITELIST:-}"
input_trimmed="${input//[[:space:]]/}"

shopt -s nocasematch
if [[ "${input_trimmed}" == "__ALL__" ]]; then
	shopt -u nocasematch
	printf 'whitelist=\n' >>"${GITHUB_OUTPUT}"
	echo "Caller forced full deploy via '__ALL__' sentinel."
	exit 0
fi
shopt -u nocasematch

if [[ -n "${input_trimmed}" ]]; then
	printf 'whitelist=%s\n' "${input}" >>"${GITHUB_OUTPUT}"
	echo "Using caller-supplied whitelist: ${input}"
	exit 0
fi

resolved="$(./scripts/meta/resolve/diff/affected_roles.sh)"

if [[ "${resolved}" == "__ALL__" ]]; then
	printf 'whitelist=\n' >>"${GITHUB_OUTPUT}"
	echo "Diff vs origin/main implies full deploy (no whitelist)."
	exit 0
fi

printf 'whitelist=%s\n' "${resolved}" >>"${GITHUB_OUTPUT}"
echo "Diff-derived whitelist: ${resolved}"
