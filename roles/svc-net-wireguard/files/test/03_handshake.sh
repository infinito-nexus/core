#!/usr/bin/env bash
# Deploy svc-net-wireguard into each node, then assert full-mesh connectivity.
# nocheck: raw-docker  # nested `docker exec` into the per-node DinD wireguard container
set -euo pipefail
: "${WIREGUARD_E2E_TIMEOUT:?}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=roles/svc-net-wireguard/files/test/nodes.sh
. "${DIR}/nodes.sh"

for n in "${NODE_NAMES[@]}"; do
    cn="${PROJECT}-${n}"
    timeout 1800 container exec "${cn}" \
        bash -c "cd /opt/src/infinito && . scripts/meta/env/load.sh; ${NODE_VENV_PY}; \"\$PY\" -m cli administration deploy dedicated ${INV_DIR}/devices.yml --id svc-net-wireguard" </dev/null
    echo "OK: ${n} deployed svc-net-wireguard"
done

# Tunnels establish in seconds; fail hard rather than wait out the full budget.
deadline=$(( $(date +%s) + 180 ))
failures=0
for n in "${NODE_NAMES[@]}"; do
    cn="${PROJECT}-${n}"
    j=0
    for m in "${NODE_NAMES[@]}"; do
        if [ "${m}" != "${n}" ]; then
            target="${TUN_PREFIX}.${NODE_OCTET[$j]}"
            ok=0
            while true; do
                if container exec "${cn}" docker exec wireguard ping -c1 -W2 "${target}" >/dev/null 2>&1; then
                    echo "OK: ${n} -> ${m} (${target}) reachable over tunnel"
                    ok=1
                    break
                fi
                if [ "$(date +%s)" -ge "${deadline}" ]; then
                    echo "FAIL: ${n} cannot reach ${m} (${target})"
                    break
                fi
                sleep 3
            done
            if [ "${ok}" -ne 1 ]; then
                failures=$(( failures + 1 ))
            fi
        fi
        j=$(( j + 1 ))
    done
done

if [ "${failures}" -ne 0 ]; then
    echo "FAIL: ${failures} mesh path(s) broken"
    exit 1
fi
echo "OK: full-mesh connectivity verified across all 6 deployed nodes"
