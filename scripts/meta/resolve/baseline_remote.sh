#!/usr/bin/env bash
#
# Output: the git remote carrying the upstream main that CI diffs against —
# either the literal `origin` or a fetch URL, usable as
# `git fetch "$(baseline_remote.sh)" main:refs/remotes/origin/main`.
#
# Env:
#   GITHUB_REPOSITORY                        - owner/repo of the running job; unset means a local clone
#   CI_SYNC_MAIN_SOURCE_REPOSITORY           - upstream repository, a GitHub URL, or a disabled value
#   CI_SYNC_MAIN_SOURCE_REPOSITORY_IS_SET    - "true" when the variable above is declared
#   CI_SYNC_MAIN_SOURCE_REPOSITORY_DEFAULT   - fallback upstream (default: infinito-nexus/core)
set -euo pipefail

if [[ -z "${GITHUB_REPOSITORY:-}" ]]; then
	echo origin
	exit 0
fi

default_source="${CI_SYNC_MAIN_SOURCE_REPOSITORY_DEFAULT:-infinito-nexus/core}"
configured_source="${CI_SYNC_MAIN_SOURCE_REPOSITORY:-}"
configured_source_is_set="${CI_SYNC_MAIN_SOURCE_REPOSITORY_IS_SET:-false}"

if [[ "${configured_source_is_set}" == "true" ]]; then
	source_repository="${configured_source}"
else
	source_repository="${default_source}"
fi

source_trimmed="${source_repository//[[:space:]]/}"
source_lower="$(printf '%s' "${source_trimmed}" | tr '[:upper:]' '[:lower:]')"

case "${source_lower}" in
"" | "false" | "0" | "no" | "off" | "none")
	echo origin
	exit 0
	;;
esac

normalize_repository() {
	local value="${1}"
	value="${value#https://github.com/}"
	value="${value#http://github.com/}"
	value="${value#ssh://git@github.com/}"
	value="${value#git@github.com:}"
	value="${value%.git}"
	printf '%s' "${value}" | tr '[:upper:]' '[:lower:]'
}

target_repository="$(normalize_repository "${GITHUB_REPOSITORY}")"
source_repository="$(normalize_repository "${source_trimmed}")"

if [[ "${source_repository}" == "${target_repository}" ]]; then
	echo origin
	exit 0
fi

if [[ "${source_repository}" != */* ]]; then
	echo "ERROR: CI_SYNC_MAIN_SOURCE_REPOSITORY must be '<owner>/<repo>', a GitHub URL, or a disabled value." >&2
	exit 1
fi

echo "https://github.com/${source_repository}.git"
