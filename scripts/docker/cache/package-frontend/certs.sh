#!/usr/bin/env bash
# shellcheck shell=bash
# Host wrapper for the in-container cert generator.
# See docs/contributing/environment/cache.md.

set -euo pipefail

: "${INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR:?Source scripts/meta/env/load.sh first}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
INNER_SCRIPT="${REPO_ROOT}/compose/package-cache-frontend/cert-gen.sh"

if [[ ! -r "${INNER_SCRIPT}" ]]; then
	echo "[package-frontend-certs] missing inner script: ${INNER_SCRIPT}" >&2
	exit 1
fi

: "${INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE:?Source scripts/meta/env/load.sh first}"
ALPINE_IMAGE="${INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE}"

exec docker run --rm \
	-v "${INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR}:/ca" \
	-v "${INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR}:/certs" \
	-v "${INNER_SCRIPT}:/work/cert-gen.sh:ro" \
	--entrypoint /bin/sh \
	"${ALPINE_IMAGE}" \
	/work/cert-gen.sh
