#!/usr/bin/env bash
# Provision the per-round test inventory. The nfs-server group is wired by
# utils/tests/swarm/extend_inventory.py, not via --include; the variant
# overlay and credential-generation variant map arrive per round from the
# matrix orchestrator and are empty in the standalone single-round path.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../utils/_context.sh"

mapfile -t includes < <(python3 -m utils.tests.swarm.derive_includes)

INV_DIR="${INFINITO_INVENTORY_DIR:-/tmp/inv}" # nocheck: swarm-test base (matrix sets it per round; /tmp/inv standalone)
mkdir -p "${INV_DIR}"

: "${INFINITO_INVENTORY_VARS_FILE:?INFINITO_INVENTORY_VARS_FILE is not set — source scripts/meta/env/load.sh first}"

provision_args=(
	--host "${MGR}"
	--include "${includes[@]}"
	--workers 2
	--vars-file "${INFINITO_INVENTORY_VARS_FILE}"
)
if [[ -n "${INFINITO_VARS_PAYLOAD:-}" ]]; then
	provision_args+=(--vars "${INFINITO_VARS_PAYLOAD}")
fi
if [[ -n "${INFINITO_APP_VARIANTS:-}" ]]; then
	provision_args+=(--app-variants "${INFINITO_APP_VARIANTS}")
fi
if [[ "$(python3 -m cli.meta.runtime)" == "github" ]]; then
	: "${INFINITO_GHCR_MIRROR_PREFIX:?required in github runtime}"
	: "${GITHUB_REPOSITORY_OWNER:?required in github runtime}"
	: "${GITHUB_REPOSITORY:?required in github runtime}"
	ghcr_namespace="$(echo "${GITHUB_REPOSITORY_OWNER}" | tr '[:upper:]' '[:lower:]')"
	ghcr_repository="$(echo "${GITHUB_REPOSITORY}" | cut -d/ -f2- | tr '[:upper:]' '[:lower:]')"
	mirrors_file="${INV_DIR}/mirrors.yml"
	python3 -m cli.contributing.mirror.resolver \
		--repo-root . \
		--ghcr-namespace "${ghcr_namespace}" \
		--ghcr-repository "${ghcr_repository}" \
		--ghcr-prefix "${INFINITO_GHCR_MIRROR_PREFIX}" \
		>"${mirrors_file}"
	provision_args+=(--mirror "${mirrors_file}")
	echo "[swarm-test] mirrors.yml generated: ${mirrors_file}"
fi

python3 -m cli.administration.inventory.provision "${INV_DIR}" "${provision_args[@]}"

cp "${INV_DIR}/host_vars/${MGR}.yml" "${INV_DIR}/host_vars/${WRK1}.yml"
cp "${INV_DIR}/host_vars/${MGR}.yml" "${INV_DIR}/host_vars/${WRK2}.yml"
cp "${INV_DIR}/host_vars/${MGR}.yml" "${INV_DIR}/host_vars/${NFS_SERVER:?}.yml"
cp "${INV_DIR}/host_vars/${MGR}.yml" "${INV_DIR}/host_vars/${BACKUP_NODE:?}.yml"
