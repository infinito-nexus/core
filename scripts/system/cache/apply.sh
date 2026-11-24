#!/usr/bin/env bash
# shellcheck shell=bash
#
# Args:
#   $1  empty: apply the pinned commit's cache declarations to the running cache stack.
#       `prepare`: before the stack starts, issue the pinned certificates and install the pinned map at INFINITO_CACHE_PACKAGE_FRONTEND_CONF.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/load.sh
source "scripts/meta/env/load.sh"
# shellcheck source=scripts/system/cache/pin.sh
source "scripts/system/cache/pin.sh"

: "${PYTHON:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_FRONTEND_CONF:?Run 'make dotenv' first}"

stage="${1:-apply}"
case "${stage}" in
apply | prepare) ;;
*)
	echo "[cache-apply] unknown stage '${stage}'; expected prepare or nothing" >&2
	exit 2
	;;
esac

if [[ "${stage}" == "apply" ]]; then
	running=0
	cache_pin_frontend_running || running=$?
	if [[ "${running}" -eq 1 ]]; then
		echo "[cache-apply] ${CACHE_PIN_FRONTEND} is not running; start it with make infra-update" >&2
	fi
	if [[ "${running}" -ne 0 ]]; then
		exit 1
	fi
	cache_pin_frontend_map || exit $?
fi

"${PYTHON}" -m cli.meta.cache.pin read >/dev/null
cache_pin_lock
sha="$("${PYTHON}" -m cli.meta.cache.pin read)"
cache_pin_materialize "${sha}"
pinned="${CACHE_PIN_CHECKOUT}"
echo "[cache-apply] serving the cache declarations of the pinned commit ${sha} from ${pinned}"
cache_pin_report_drift "${pinned}"
cache_pin_export_env "${pinned}"

if [[ "${stage}" == "apply" ]]; then
	echo "[cache-apply] creating the Nexus proxy repositories"
	nexus="$("${PYTHON}" -m cli.administration.infra cache-name package)"
	nexus_port="$("${PYTHON}" -m cli.administration.infra cache-port package http)"
	(
		CACHE_PIN_CALLER="$(pwd -P)"
		# shellcheck disable=SC2329,SC2317
		docker() { (unset -f docker && cd "${CACHE_PIN_CALLER}" && cache_pin_docker "$@"); }
		export -f docker cache_pin_docker
		export CACHE_PIN_CALLER INFINITO_CACHE_PACKAGE_CONTAINER="${nexus}" INFINITO_CACHE_PACKAGE_PORT="${nexus_port}" INFINITO_CACHE_PACKAGE_EXEC_MODE=docker INFINITO_CACHE_PACKAGE_REST_HOST=127.0.0.1
		cd "${pinned}" && bash roles/svc-cache-package/files/shell/bootstrap.sh
	)
fi

echo "[cache-apply] issuing the frontend leaf certificates"
(cd "${pinned}" && bash roles/svc-cache-package/files/shell/certs.sh)

if [[ "${stage}" == "prepare" ]]; then
	echo "[cache-apply] installing the pinned map at ${INFINITO_CACHE_PACKAGE_FRONTEND_CONF}"
	cache_pin_install_map "${pinned}" "${INFINITO_CACHE_PACKAGE_FRONTEND_CONF}"
	exit 0
fi

echo "[cache-apply] installing the pinned map into ${CACHE_PIN_FRONTEND_MAP}"
cache_pin_install_map "${pinned}" "${CACHE_PIN_FRONTEND_MAP}"

echo "[cache-apply] reloading ${CACHE_PIN_FRONTEND}"
cache_pin_docker exec "${CACHE_PIN_FRONTEND}" nginx -t
cache_pin_docker exec "${CACHE_PIN_FRONTEND}" nginx -s reload

"${PYTHON}" -m cli.meta.cache.pin applied "${sha}"
echo "[cache-apply] done: ${sha} applied. Recreate this checkout's runner to pick up new DNS hijacks:"
echo "[cache-apply]   make compose-up"
