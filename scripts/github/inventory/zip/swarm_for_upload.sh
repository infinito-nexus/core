#!/usr/bin/env bash
set -euo pipefail

: "${APP_ID:?APP_ID is required (matrix.apps)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh
: "${INFINITO_INVENTORY_DIR:?INFINITO_INVENTORY_DIR must be resolved by scripts/meta/env/load.sh}"

out="/tmp/inventory-swarm-${APP_ID}.zip"
stage="/tmp/inventory-swarm-${APP_ID}"
sudo rm -rf "${stage}" 2>/dev/null || rm -rf "${stage}" 2>/dev/null || true
mkdir -p "${stage}"

shopt -s nullglob
found=0
for d in "${INFINITO_INVENTORY_DIR}" "${INFINITO_INVENTORY_DIR}"-*; do
	[[ -d "${d}" ]] || continue
	sudo cp -a "${d}" "${stage}/$(basename "${d}")" 2>/dev/null || cp -a "${d}" "${stage}/$(basename "${d}")"
	found=1
done

if [[ "${found}" -eq 0 ]]; then
	echo "::error::No inventory found under ${INFINITO_INVENTORY_DIR}* on the runner." >&2
	exit 1
fi

sudo chown -R "$(id -u):$(id -g)" "${stage}" 2>/dev/null || true
(cd /tmp && zip -r "${out}" "inventory-swarm-${APP_ID}")
