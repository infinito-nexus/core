#!/usr/bin/env bash
# shellcheck shell=bash
#
# Args (sourced by apply.sh and declare.sh from the checkout root, never run):
#   cache_pin_root: sets CACHE_PIN_ROOT to the resolved INFINITO_CACHE_PIN_ROOT and creates it; refuses a relative root or one inside this checkout.
#   cache_pin_lock: holds an exclusive lock on CACHE_PIN_ROOT/.lock on fd 9 until cache_pin_unlock or the shell exits.
#   cache_pin_unlock: releases the lock cache_pin_lock holds.
#   cache_pin_docker ARGS: runs docker ARGS on the infra runner's daemon, where the cache containers run.
#   cache_pin_frontend_running: sets CACHE_PIN_FRONTEND and succeeds while it runs; returns 1 when it does not, 2 when docker ps fails.
#   cache_pin_frontend_map: sets CACHE_PIN_FRONTEND_MAP to the map CACHE_PIN_FRONTEND mounts; refuses one outside CACHE_PIN_ROOT.
#   cache_pin_materialize SHA: sets CACHE_PIN_CHECKOUT to the checkout of SHA below CACHE_PIN_ROOT; refuses a symlinked checkout and one without its map.
#   cache_pin_export_env DIR: exports the declaration-derived keys the checkout in DIR computes.
#   cache_pin_report_drift DIR: names this checkout's declarations that differ from DIR; never fails.
#   cache_pin_install_map DIR TARGET: copies the map of DIR onto TARGET in place and leaves it read-only.

CACHE_PIN_MAP="compose/package-cache-frontend/upstreams.conf"
CACHE_PIN_EXCLUDES=(":(exclude)locale" ":(exclude)tests" ":(exclude)docs")
CACHE_PIN_MOUNT_TARGET="/etc/nginx/conf.d/upstreams.conf"

cache_pin_root() {
	local root checkout
	: "${INFINITO_CACHE_PIN_ROOT:?Run 'make dotenv' first}"
	if [[ "${INFINITO_CACHE_PIN_ROOT}" != /* ]]; then
		echo "[cache-pin] INFINITO_CACHE_PIN_ROOT=${INFINITO_CACHE_PIN_ROOT} is not an absolute path" >&2
		return 1
	fi
	root="$(realpath -m -- "${INFINITO_CACHE_PIN_ROOT}")"
	checkout="$(pwd -P)"
	if [[ "${root}/" == "${checkout}/"* ]]; then
		echo "[cache-pin] INFINITO_CACHE_PIN_ROOT=${INFINITO_CACHE_PIN_ROOT} lies inside the checkout ${checkout}" >&2
		return 1
	fi
	mkdir -p "${root}"
	# shellcheck disable=SC2034
	CACHE_PIN_ROOT="${root}"
}

cache_pin_lock() {
	cache_pin_root || return 1
	exec 9>"${CACHE_PIN_ROOT}/.lock"
	flock 9
}

cache_pin_unlock() {
	exec 9>&-
}

cache_pin_docker() {
	"${PYTHON:?Source scripts/meta/env/load.sh first}" -m cli.administration.infra docker "$@"
}

cache_pin_frontend_running() {
	local names
	CACHE_PIN_FRONTEND="$("${PYTHON:?Source scripts/meta/env/load.sh first}" -m cli.administration.infra cache-name frontend)" || return 2
	if ! names="$(cache_pin_docker ps --format '{{.Names}}')"; then
		echo "[cache-pin] docker ps failed, so it is unknown whether ${CACHE_PIN_FRONTEND} runs" >&2
		return 2
	fi
	grep -qx -- "${CACHE_PIN_FRONTEND}" <<<"${names}"
}

cache_pin_frontend_map() {
	local mounted
	cache_pin_root || return 1
	mounted="$(cache_pin_docker inspect -f \
		"{{range .Mounts}}{{if eq .Destination \"${CACHE_PIN_MOUNT_TARGET}\"}}{{.Source}}{{end}}{{end}}" \
		"${CACHE_PIN_FRONTEND}")" || return 1
	if [[ -z "${mounted}" ]]; then
		echo "[cache-pin] ${CACHE_PIN_FRONTEND} mounts no map at ${CACHE_PIN_MOUNT_TARGET}" >&2
		return 1
	fi
	if [[ "$(realpath -m -- "${mounted}")" != "${CACHE_PIN_ROOT}/"* ]]; then
		echo "[cache-pin] ${CACHE_PIN_FRONTEND} mounts its map from ${mounted}, outside INFINITO_CACHE_PIN_ROOT ${CACHE_PIN_ROOT}; it serves another pin root. Check that INFINITO_CACHE_PACKAGE_FRONTEND_CONF in .env and in your shell lies below INFINITO_CACHE_PIN_ROOT, then recreate it with make compose-up in the checkout that owns the cache stack" >&2
		return 1
	fi
	# shellcheck disable=SC2034
	CACHE_PIN_FRONTEND_MAP="${mounted}"
}

cache_pin_materialize() {
	local sha="$1" dir scratch
	cache_pin_root || return 1
	dir="${CACHE_PIN_ROOT}/${sha}"
	# shellcheck disable=SC2034
	CACHE_PIN_CHECKOUT="${dir}"
	if [[ -L "${dir}" ]]; then
		echo "[cache-pin] ${dir} is a symlink; a pinned checkout is a directory below INFINITO_CACHE_PIN_ROOT" >&2
		return 1
	fi
	if [[ -d "${dir}" ]]; then
		if [[ ! -f "${dir}/${CACHE_PIN_MAP}" ]]; then
			echo "[cache-pin] ${dir} has no ${CACHE_PIN_MAP}; remove it and declare ${sha} again" >&2
			return 1
		fi
		return 0
	fi
	echo "[cache-pin] materializing ${sha} at ${dir}" >&2
	scratch="$(mktemp -d "${CACHE_PIN_ROOT}/.${sha}.XXXXXX")"
	# shellcheck disable=SC2064
	trap "rm -rf -- '${scratch}'" EXIT
	if ! git archive --format=tar "${sha}" -- . "${CACHE_PIN_EXCLUDES[@]}" | tar -x -C "${scratch}"; then
		echo "[cache-pin] could not extract ${sha}" >&2
		return 1
	fi
	if ! (cd "${scratch}" && PYTHONDONTWRITEBYTECODE=1 INFINITO_CACHE_PIN_FILE='' INFINITO_CACHE_PACKAGE_FRONTEND_CONF="${scratch}/${CACHE_PIN_MAP}" "${PYTHON}" -m cli.meta.cache >&2); then
		echo "[cache-pin] could not render the cache files of ${sha}" >&2
		return 1
	fi
	if [[ ! -f "${scratch}/${CACHE_PIN_MAP}" ]]; then
		echo "[cache-pin] rendering ${sha} left no ${CACHE_PIN_MAP}" >&2
		return 1
	fi
	if ! mv -T "${scratch}" "${dir}" 2>/dev/null; then
		[[ -d "${dir}" && ! -L "${dir}" ]] || return 1
	fi
	rm -rf -- "${scratch}"
	trap - EXIT
}

cache_pin_export_env() {
	local lines line
	if ! lines="$(cd "$1" && PYTHONDONTWRITEBYTECODE=1 "${PYTHON}" -m cli.meta.cache.pin env)"; then
		echo "[cache-pin] could not read the cache declarations of $1" >&2
		return 1
	fi
	while IFS= read -r line; do
		export "${line%%=*}=${line#*=}"
	done <<<"${lines}"
}

cache_pin_report_drift() {
	if ! "${PYTHON}" -m cli.meta.cache.pin drift "$1"; then
		echo "[cache-pin] WARNING: could not compare this checkout's cache: declarations with $1" >&2
	fi
}

cache_pin_install_map() {
	local source="$1/${CACHE_PIN_MAP}" target="$2"
	mkdir -p "$(dirname "${target}")"
	if [[ -e "${target}" ]]; then
		chmod u+w "${target}"
	fi
	cp -- "${source}" "${target}"
	chmod a-w "${target}"
}
