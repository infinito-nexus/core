#!/usr/bin/env bash
# shellcheck shell=bash
#
# Wraps a command and, on apt "Release expired" / "Valid-Until expired"
# failure, invalidates the Nexus apt-proxy caches via REST and re-runs once.
# Usage: deploy_with_cache_retry "<label>" -- <cmd> [args...]

_CACHE_RETRY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_CACHE_RETRY_REPO_ROOT="$(cd "${_CACHE_RETRY_DIR}/../../../../.." && pwd)"

_cache_retry_stale_pattern='Release file .*is expired|Valid-Until.*expired'

# Used when the Nexus API discovery call fails; mirrors scripts/docker/cache/package.sh.
_CACHE_RETRY_FALLBACK_REPOS=(apt-debian apt-debian-security apt-ubuntu apt-ubuntu-security)

_cache_retry_nexus_invalidate() {
	local repo="$1"
	local rest="http://127.0.0.1:8081/service/rest/v1/repositories/${repo}/invalidate-cache"
	local code
	code="$(docker exec infinito-package-cache curl -sS -o /dev/null -w '%{http_code}' \
		-u "admin:${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}" \
		-X POST "${rest}" 2>/dev/null || echo 000)"
	if [[ "${code}" =~ ^2[0-9][0-9]$ ]]; then
		echo "[cache-retry] invalidate-cache OK (${code}): ${repo}"
	else
		echo "[cache-retry] WARN: invalidate-cache failed (${code}) for ${repo} — continuing"
	fi
}

_cache_retry_list_apt_proxy_repos() {
	local json
	json="$(docker exec infinito-package-cache curl -sS \
		-u "admin:${INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD}" \
		"http://127.0.0.1:8081/service/rest/v1/repositories" 2>/dev/null)" || return 1
	[[ -z "${json}" ]] && return 1
	printf '%s' "${json}" |
		"${PYTHON:-python3}" "${_CACHE_RETRY_REPO_ROOT}/utils/nexus/list_apt_proxy_repos.py" \
			2>/dev/null ||
		return 1
	return 0
}

cache_retry_recover() {
	# Defensive re-source: helper may be invoked outside the wrapping deploy script.
	# shellcheck disable=SC1091  # path is runtime-resolved through REPO_ROOT
	source "${REPO_ROOT:-${PWD}}/scripts/meta/env/load.sh"

	local repos=()
	local discovered
	if discovered="$(_cache_retry_list_apt_proxy_repos)"; then
		while IFS= read -r _line; do
			[[ -n "${_line}" ]] && repos+=("${_line}")
		done <<<"${discovered}"
		echo "[cache-retry] discovered apt-proxy repos from Nexus: ${repos[*]}"
	else
		repos=("${_CACHE_RETRY_FALLBACK_REPOS[@]}")
		echo "[cache-retry] WARN: could not query Nexus — using fallback list: ${repos[*]}"
	fi

	local repo
	for repo in "${repos[@]}"; do
		echo "[cache-retry] Nexus invalidate-cache: ${repo}"
		_cache_retry_nexus_invalidate "${repo}"
	done

	echo "[cache-retry] docker builder prune -af..."
	docker builder prune -af >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
	echo "[cache-retry] docker image prune -af..."
	docker image prune -af >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
}

# Toggle errexit around the pipeline so a wrapped non-zero exit reaches the caller
# instead of killing the script before the stale-cache match is evaluated.
_cache_retry_run_capture() {
	local log="$1"
	shift
	__cache_retry_rc=0
	local _prev_e=0
	[[ $- == *e* ]] && _prev_e=1
	set +e
	"$@" 2>&1 | tee "${log}"
	__cache_retry_rc=${PIPESTATUS[0]}
	[[ "${_prev_e}" -eq 1 ]] && set -e
	return 0
}

deploy_with_cache_retry() {
	local label="${1:-deploy}"
	shift
	if [[ "${1:-}" == "--" ]]; then shift; fi

	local log sanitized
	sanitized="${label//[^A-Za-z0-9._-]/-}"
	log="$(mktemp -t "deploy-${sanitized:0:80}.XXXXXX.log")"

	_cache_retry_run_capture "${log}" "$@"
	local rc=${__cache_retry_rc}

	if [[ "${rc}" -eq 0 ]]; then
		rm -f "${log}"
		return 0
	fi

	if ! grep -qE "${_cache_retry_stale_pattern}" "${log}" 2>/dev/null; then
		rm -f "${log}"
		return "${rc}"
	fi

	echo
	echo "[cache-retry] Stale apt Release file detected in '${label}' output."
	echo "[cache-retry] Invalidating Nexus apt-proxy caches, pruning Docker caches, re-running once."
	cache_retry_recover

	echo
	echo "[cache-retry] Re-running: ${label}"
	: >"${log}"
	_cache_retry_run_capture "${log}" "$@"
	rc=${__cache_retry_rc}

	rm -f "${log}"
	return "${rc}"
}
