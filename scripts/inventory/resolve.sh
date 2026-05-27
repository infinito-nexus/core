#!/usr/bin/env bash
set -euo pipefail

# Resolve INFINITO_INVENTORY_DIR based on Makefile-provided environment.
#
# Required env (must be set by Makefile):
#   INFINITO_RUNNING_ON_ACT     : true|false
#   INFINITO_RUNNING_ON_GITHUB  : true|false
#
# Uses:
#   HOME
#
# Output:
#   Prints resolved INFINITO_INVENTORY_DIR to stdout (single line)
#   (no mkdir, no side-effects)

require_env() {
	local name="$1"
	if [[ -z "${!name:-}" ]]; then
		echo "[FATAL] ${name} must be set by Makefile" >&2
		exit 2
	fi
}

normalize_bool() {
	local v="${1:-}"
	case "${v}" in
	true | false) printf '%s' "${v}" ;;
	*)
		echo "[FATAL] invalid boolean value: '${v}' (expected true|false)" >&2
		exit 2
		;;
	esac
}

require_env "INFINITO_RUNNING_ON_ACT"
require_env "INFINITO_RUNNING_ON_GITHUB"
: "${HOME:?HOME must be set}"

INFINITO_RUNNING_ON_ACT="$(normalize_bool "${INFINITO_RUNNING_ON_ACT}")"
INFINITO_RUNNING_ON_GITHUB="$(normalize_bool "${INFINITO_RUNNING_ON_GITHUB}")"

if [[ "${INFINITO_RUNNING_ON_ACT}" == "true" ]]; then
	INFINITO_INVENTORY_DIR="${HOME}/inventories/act"
elif [[ "${INFINITO_RUNNING_ON_GITHUB}" == "true" ]]; then
	INFINITO_INVENTORY_DIR="${HOME}/inventories/github"
else
	INFINITO_INVENTORY_DIR="${HOME}/inventories/localhost"
fi

# IMPORTANT: single-line output for Makefile $(shell ...)
printf '%s\n' "${INFINITO_INVENTORY_DIR}"
