#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REPOSITORY:?Missing GITHUB_REPOSITORY}"

decide_only="${CI_SYNC_MAIN_DECIDE_ONLY:-false}"

# Param: $1 - "true" when the mirror push will run, "false" when it is skipped
decide() {
	local will_sync="${1}"
	if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
		printf 'sync=%s\n' "${will_sync}" >>"${GITHUB_OUTPUT}"
	fi
	if [[ "${decide_only}" == "true" || "${will_sync}" != "true" ]]; then
		exit 0
	fi
}

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
	decide false
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
	decide false
fi

if [[ "${source_repository}" != */* ]]; then
	echo "ERROR: CI_SYNC_MAIN_SOURCE_REPOSITORY must be '<owner>/<repo>', a GitHub URL, or a disabled value." >&2
	exit 1
fi

decide true

if [[ -z "${CI_SYNC_MAIN_PUSH_TOKEN:-}" ]]; then
	echo "ERROR: CI_SYNC_MAIN_PUSH_TOKEN is empty; the mirror push needs an app installation token carrying Workflows:write." >&2
	exit 1
fi

echo "Syncing ${GITHUB_REPOSITORY}:main from ${source_repository}:main."
git fetch "https://github.com/${source_repository}.git" main:refs/remotes/main-sync-source/main --force

git config --local credential.helper ""
# shellcheck disable=SC2016 # single quotes are the point: the helper expands the token at call time, so it never reaches argv or .git/config
git config --local --add credential.helper '!f() { printf "username=x-access-token\npassword=%s\n" "${CI_SYNC_MAIN_PUSH_TOKEN}"; }; f'

git push origin refs/remotes/main-sync-source/main:refs/heads/main --force
