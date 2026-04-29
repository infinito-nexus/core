#!/usr/bin/env bash
# shellcheck shell=bash
#
# Wipe the on-disk caches that the `cache` compose profile populates:
# the rpardini/docker-registry-proxy mirror + MITM CA, and the
# Sonatype Nexus 3 OSS data dir. Both live under /var/cache/infinito/
# core/<service>/ by default; the per-cache env scripts under
# scripts/meta/env/cache/ are sourced first so a custom HOST_PATH
# from the developer's environment is honoured.
#
# Removing the directories is enough: docker compose recreates them
# on the next `up` thanks to `bind: { create_host_path: true }`. For
# the Nexus side, the next bootstrap rotates a fresh admin password
# and re-creates blobstore + proxy repos.
#
# Use `make cache-clean` rather than calling this script directly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/cache/registry.sh
source "scripts/meta/env/cache/registry.sh"
# shellcheck source=scripts/meta/env/cache/package.sh
source "scripts/meta/env/cache/package.sh"

# Stop any running cache containers first so wipe is safe (a running
# Nexus would re-create files mid-rm). `docker compose down` of the
# whole stack would also kill the runner, which is too destructive;
# scope to the two cache services explicitly.
if docker ps --format '{{.Names}}' | grep -qE '^infinito-(registry|package)-cache$'; then
	echo "[cache-clean] stopping infinito-registry-cache + infinito-package-cache"
	docker stop infinito-registry-cache infinito-package-cache 2>/dev/null || true
	docker rm infinito-registry-cache infinito-package-cache 2>/dev/null || true
fi

PATHS=(
	"${INFINITO_REGISTRY_CACHE_HOST_PATH}"
	"${INFINITO_REGISTRY_CACHE_CA_HOST_PATH}"
	"${INFINITO_PACKAGE_CACHE_HOST_PATH}"
)

# Remove each cache path individually (keeps the parent /var/cache/
# infinito/ dir alive so other future cache services can co-locate).
# Use sudo when the path is root-owned (Nexus chowns its data dir to
# uid 200 for the in-container nexus user) so the rm does not silently
# leave half-deleted state behind.
remove_path() {
	local p="$1"
	[[ -z "${p}" ]] && return 0
	if [[ ! -e "${p}" ]]; then
		echo "[cache-clean] not present, skipping: ${p}"
		return 0
	fi
	if [[ -w "${p}" ]] || [[ -O "${p}" ]]; then
		echo "[cache-clean] removing: ${p}"
		rm -rf -- "${p}"
	else
		echo "[cache-clean] removing (sudo): ${p}"
		sudo rm -rf -- "${p}"
	fi
}

remove_path "${PATHS[0]}"
remove_path "${PATHS[1]}"
remove_path "${PATHS[2]}"

echo "[cache-clean] done. Re-run 'make up' to recreate empty caches."
