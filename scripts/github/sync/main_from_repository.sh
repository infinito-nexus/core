#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REPOSITORY:?Missing GITHUB_REPOSITORY}"

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
	echo "Main sync skipped because CI_SYNC_MAIN_SOURCE_REPOSITORY is disabled."
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
	echo "Main sync skipped because source repository matches current repository: ${GITHUB_REPOSITORY}."
	exit 0
fi

if [[ "${source_repository}" != */* ]]; then
	echo "ERROR: CI_SYNC_MAIN_SOURCE_REPOSITORY must be '<owner>/<repo>', a GitHub URL, or a disabled value." >&2
	exit 1
fi

echo "Syncing ${GITHUB_REPOSITORY}:main from ${source_repository}:main."
git fetch "https://github.com/${source_repository}.git" main:refs/remotes/main-sync-source/main --force
git push origin refs/remotes/main-sync-source/main:refs/heads/main --force
