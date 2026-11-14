#!/usr/bin/env bash
set -euo pipefail

: "${INFINITO_BUILD_CACHE_MAX_SIZE:?Run 'make dotenv' to generate the .env single source of truth}"

prune_help="$(docker builder prune --help)"
if grep -q -- '--max-used-space' <<<"${prune_help}"; then
	keep_flag="--max-used-space"
elif grep -q -- '--keep-storage' <<<"${prune_help}"; then
	keep_flag="--keep-storage"
else
	echo "[build] ERROR: 'docker builder prune' accepts neither --max-used-space nor --keep-storage; cannot cap the build cache at INFINITO_BUILD_CACHE_MAX_SIZE=${INFINITO_BUILD_CACHE_MAX_SIZE}" >&2
	exit 1
fi

echo "[build] Pruning the build cache to INFINITO_BUILD_CACHE_MAX_SIZE=${INFINITO_BUILD_CACHE_MAX_SIZE} (${keep_flag})"
docker builder prune --force "${keep_flag}" "${INFINITO_BUILD_CACHE_MAX_SIZE}"
