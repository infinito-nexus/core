#!/usr/bin/env bash
set -euo pipefail

: "${APP_ID:?APP_ID is required (matrix.apps)}"

out="/tmp/inventory-compose-${APP_ID}.zip"
stage="/tmp/inventory-compose-${APP_ID}"
rm -rf "${stage}"
mkdir -p "${stage}"

mapfile -t containers < <(docker ps --format '{{.Names}}' | grep '^infinito_nexus_' || true)
for c in "${containers[@]}"; do
	docker cp "${c}:/root/inventories" "${stage}/${c}-inventories" 2>/dev/null || true
done

if [[ -d "${stage}" && -n "$(ls -A "${stage}" 2>/dev/null)" ]]; then
	(cd /tmp && zip -r "${out}" "inventory-compose-${APP_ID}")
else
	echo "No inventories captured from compose containers"
fi
