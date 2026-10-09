#!/usr/bin/env bash
# shellcheck shell=bash
# nocheck: raw-docker  this runs on the developer's host against the dev cache stack, where the `container` wrapper is not on PATH
#
# Install this checkout's cache declarations into the running cache stack:
# the Nexus proxy repositories, the frontend's leaf certificates, and the
# nginx upstream map the frontend serves. A checkout that declares a new
# cache host needs all three before a client reaches it.
#
# The frontend belongs to whichever checkout owns the cache stack, so the
# map is copied onto the path that container actually mounts rather than
# only rendered here. The map is generated, never tracked, so the owning
# checkout restores its own set by running this script or `make dotenv`.
#
# Use `make cache-apply` rather than calling this script directly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/load.sh
source "scripts/meta/env/load.sh"

: "${INFINITO_CACHE_PACKAGE_FRONTEND_CONF:?Run 'make dotenv' first}"

FRONTEND="infinito-package-cache-frontend"
MOUNT_TARGET="/etc/nginx/conf.d/upstreams.conf"

if ! docker ps --format '{{.Names}}' | grep -qx "${FRONTEND}"; then
	echo "[cache-apply] ${FRONTEND} is not running; start the cache stack first" >&2
	exit 1
fi

echo "[cache-apply] rendering this checkout's cache artefacts"
python3 -m cli.meta.cache

echo "[cache-apply] creating the Nexus proxy repositories"
bash roles/svc-cache-package/files/shell/bootstrap.sh

echo "[cache-apply] issuing the frontend leaf certificates"
bash roles/svc-cache-package/files/shell/certs.sh

mounted="$(docker inspect -f \
	"{{range .Mounts}}{{if eq .Destination \"${MOUNT_TARGET}\"}}{{.Source}}{{end}}{{end}}" \
	"${FRONTEND}")"

if [[ -z "${mounted}" ]]; then
	echo "[cache-apply] ${FRONTEND} mounts no map at ${MOUNT_TARGET}" >&2
	exit 1
fi

if [[ "${mounted}" != "${INFINITO_CACHE_PACKAGE_FRONTEND_CONF}" ]]; then
	echo "[cache-apply] installing this checkout's map into ${mounted}"
	cp -- "${INFINITO_CACHE_PACKAGE_FRONTEND_CONF}" "${mounted}"
fi

echo "[cache-apply] reloading ${FRONTEND}"
docker exec "${FRONTEND}" nginx -t
docker exec "${FRONTEND}" nginx -s reload

echo "[cache-apply] done. Recreate this checkout's runner to pick up new DNS hijacks:"
echo "[cache-apply]   make compose-up"
