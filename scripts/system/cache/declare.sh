#!/usr/bin/env bash
# shellcheck shell=bash
#
# Args:
#   $1  branch, tag or commit SHA; resolved to the full commit the pin names, refused when it names no commit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/load.sh
source "scripts/meta/env/load.sh"
# shellcheck source=scripts/system/cache/pin.sh
source "scripts/system/cache/pin.sh"

: "${PYTHON:?Source scripts/meta/env/load.sh first}"

ref="${1:?usage: make cache-declare ref=<commit>}"

sha="$("${PYTHON}" -m cli.meta.cache.pin resolve "${ref}")"
if ! git cat-file -e "${sha}:cli/meta/cache/pin/__main__.py" 2>/dev/null; then
	echo "[cache-declare] ${sha} (${ref}) predates the cache pin; declare a commit that contains cli/meta/cache/pin" >&2
	exit 2
fi
cache_pin_lock
cache_pin_materialize "${sha}"
"${PYTHON}" -m cli.meta.cache.pin declare "${sha}" >/dev/null
cache_pin_unlock
echo "[cache-declare] pinned ${sha} (${ref}) at ${INFINITO_CACHE_PIN_FILE}, checkout ${CACHE_PIN_CHECKOUT}"

running=0
cache_pin_frontend_running || running=$?
case "${running}" in
0) ;;
1)
	echo "[cache-declare] ${CACHE_PIN_FRONTEND} is not running; make infra-update, or the next make infra-up or make compose-up that starts the infra runner, applies ${sha}"
	exit 0
	;;
*)
	echo "[cache-declare] ${sha} is pinned but not applied; run make cache-apply once docker answers" >&2
	exit 1
	;;
esac

if ! bash "${SCRIPT_DIR}/apply.sh"; then
	echo "[cache-declare] ${sha} is pinned but not applied; see the reason above" >&2
	exit 1
fi
