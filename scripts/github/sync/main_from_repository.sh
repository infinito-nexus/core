#!/usr/bin/env bash
#
# Env:
#   GITHUB_REPOSITORY   - owner/repo of the running job, whose main is overwritten
#   CI_SYNC_MAIN_TOKEN  - fine-grained token for GITHUB_REPOSITORY only, with Contents and Workflows write
#   CI_SYNC_MAIN_SOURCE_REPOSITORY, CI_SYNC_MAIN_SOURCE_REPOSITORY_IS_SET,
#   CI_SYNC_MAIN_SOURCE_REPOSITORY_DEFAULT - the source of main, see scripts/meta/resolve/baseline_remote.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

: "${GITHUB_REPOSITORY:?Missing GITHUB_REPOSITORY}"

source_remote="$(bash "${REPO_ROOT}/scripts/meta/resolve/baseline_remote.sh")"
if [[ "${source_remote}" == "origin" ]]; then
	echo "Main sync skipped: no source repository other than ${GITHUB_REPOSITORY} is configured."
	exit 0
fi

if [[ -z "${CI_SYNC_MAIN_TOKEN:-}" ]]; then
	echo "ERROR: secret CI_SYNC_MAIN_TOKEN is not set, so ${GITHUB_REPOSITORY}:main cannot be synced from ${source_remote}." >&2
	echo "Create it as described in docs/contributing/tools/github/actions/secrets.md, or disable the sync through the repository variable CI_SYNC_MAIN_SOURCE_REPOSITORY." >&2
	exit 1
fi

echo "Syncing ${GITHUB_REPOSITORY}:main from ${source_remote}."
git fetch "${source_remote}" main:refs/remotes/main-sync-source/main --force

auth="$(printf 'x-access-token:%s' "${CI_SYNC_MAIN_TOKEN}" | base64 -w0)"
GIT_CONFIG_COUNT=1 \
	GIT_CONFIG_KEY_0="http.extraheader" \
	GIT_CONFIG_VALUE_0="AUTHORIZATION: basic ${auth}" \
	git push "https://github.com/${GITHUB_REPOSITORY}.git" refs/remotes/main-sync-source/main:refs/heads/main --force
