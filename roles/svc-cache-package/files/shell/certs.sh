#!/usr/bin/env bash
# shellcheck shell=bash
# nocheck: raw-docker  this runs on the developer's host to bring the dev cache up, where the `container` wrapper is not on PATH (verified: `which container` -> not found)
# Host wrapper for the in-container cert generator.
# See docs/contributing/environment/cache.md.

set -euo pipefail

: "${INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR:?Source scripts/meta/env/load.sh first}"
: "${INFINITO_CACHE_TLS_HOSTS:?Source scripts/meta/env/load.sh first}"

ROLE_FILES="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${ROLE_FILES}/../../../.." && pwd)"
INNER_SCRIPT="${ROLE_FILES}/cert-gen.sh"
RETRY="${REPO_ROOT}/scripts/github/runner/pull_with_retry.sh"

if [[ ! -r "${INNER_SCRIPT}" ]]; then
	echo "[package-frontend-certs] missing inner script: ${INNER_SCRIPT}" >&2
	exit 1
fi

: "${INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE:?Source scripts/meta/env/load.sh first}"
ALPINE_IMAGE="${INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE}"

if [[ -x "${RETRY}" ]]; then
	MAX_ATTEMPTS=3 RETRY_DELAY_SECONDS=10 "${RETRY}" "${ALPINE_IMAGE}" ||
		echo "[package-frontend-certs] could not pull ${ALPINE_IMAGE}; falling back to a cached copy" >&2
else
	docker pull "${ALPINE_IMAGE}" >/dev/null 2>&1 ||
		echo "[package-frontend-certs] could not pull ${ALPINE_IMAGE}; falling back to a cached copy" >&2
fi

exec docker run --rm \
	-e "INFINITO_CACHE_TLS_HOSTS=${INFINITO_CACHE_TLS_HOSTS}" \
	-v "${INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR}:/ca" \
	-v "${INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR}:/certs" \
	-v "${INNER_SCRIPT}:/work/cert-gen.sh:ro" \
	--entrypoint /bin/sh \
	"${ALPINE_IMAGE}" \
	/work/cert-gen.sh
