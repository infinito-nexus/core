#!/usr/bin/env bash
# shellcheck shell=bash
# Param: $1 the image's own entrypoint script, run with the idle window of CACHE_MAX_IDLE_DAYS in its proxy_cache_path line
set -euo pipefail

: "${CACHE_MAX_SIZE:?Set by the svc-registry-cache env from services.cache.multi_proxy.max_size}"
: "${CACHE_MAX_IDLE_DAYS:?Set by the svc-registry-cache env from services.cache.max_idle_days}"
: "${REGISTRIES?Set by the svc-registry-cache env from services.cache.multi_proxy.registries}"
export REGISTRIES="${REGISTRIES//,/ }"

original="${1:?Pass the image entrypoint to wrap}"
shift

if [[ ! "${CACHE_MAX_IDLE_DAYS}" =~ ^[1-9][0-9]*$ ]]; then
	echo "[registry-cache] CACHE_MAX_IDLE_DAYS must be a positive number of days, got '${CACHE_MAX_IDLE_DAYS}'" >&2
	exit 1
fi

# shellcheck disable=SC2016
image_line='max_size=$CACHE_MAX_SIZE inactive=60d '
bounded_line="${image_line/60d/${CACHE_MAX_IDLE_DAYS}d}"
script="$(<"${original}")"
if [[ "${script}" != *"${image_line}"* ]]; then
	echo "[registry-cache] ${original} no longer writes '${image_line}'; check the pinned image before bounding its cache" >&2
	exit 1
fi

patched="$(mktemp)"
printf '%s\n' "${script//"${image_line}"/"${bounded_line}"}" >"${patched}"
exec bash "${patched}" "$@"
