#!/usr/bin/env bash
# Deploy the workstation clients (one behind NAT), then assert each client<->server
# tunnel, the NAT masquerade rule, and the auto-derived client MTU.
# nocheck: raw-docker  # nested docker exec into the per-node wireguard container
set -euo pipefail
: "${WIREGUARD_E2E_TIMEOUT:?}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=roles/svc-net-wireguard/files/test/nodes.sh
. "${DIR}/nodes.sh"

is_nat() {
    local c="$1" x
    for x in "${NAT_NODES[@]}"; do
        [ "${x}" = "${c}" ] && return 0
    done
    return 1
}

# Deploy the clients. Behind-NAT workstations add the 'nat' flavor.
for c in "${CLIENT_NODES[@]}"; do
    cn="${PROJECT}-${c}"
    if is_nat "${c}"; then
        flavor_json='{"WIREGUARD_FLAVOR": ["client", "nat"]}'
    else
        flavor_json='{"WIREGUARD_FLAVOR": ["client"]}'
    fi
    timeout 1800 container exec "${cn}" \
        bash -c "cd /opt/src/infinito && . scripts/meta/env/load.sh; ${NODE_VENV_PY}; \"\$PY\" -m cli administration deploy dedicated ${INV_DIR}/devices.yml --id svc-net-wireguard --password-file ${INV_DIR}/.password -e ansible_connection=local -e DOCKER_IN_CONTAINER=true -e SYS_SVC_CONTAINER_STORAGE_DRIVER=vfs -e '${flavor_json}'" </dev/null
    echo "OK: ${c} deployed (${flavor_json})"
done

# Tunnel state up front for debugging.
for n in "${NODE_NAMES[@]}"; do
    echo "--- wg show on ${n} ---"
    container exec "${PROJECT}-${n}" docker exec wireguard wg show 2>&1 || true
done

deadline=$(( $(date +%s) + 180 ))
failures=0

ping_check() {
    local node="$1" target="$2" label="$3"
    while true; do
        if container exec "${PROJECT}-${node}" docker exec wireguard ping -c1 -W2 "${target}" >/dev/null 2>&1; then
            echo "OK: ${label} (${target}) reachable over tunnel"
            return 0
        fi
        if [ "$(date +%s)" -ge "${deadline}" ]; then
            echo "FAIL: ${label} cannot reach ${target}"
            return 1
        fi
        sleep 3
    done
}

# Connectivity per pair: client -> server (.1) and server -> client (.2).
i=0
for s in "${SERVER_NODES[@]}"; do
    c="${CLIENT_NODES[$i]}"
    ping_check "${c}" "${WG_SERVER_IP}" "${c} -> ${s}" || failures=$(( failures + 1 ))
    ping_check "${s}" "${WG_CLIENT_IP}" "${s} -> ${c}" || failures=$(( failures + 1 ))
    i=$(( i + 1 ))
done

# NAT: the masquerade rule must be present on every behind-NAT workstation node.
for c in "${NAT_NODES[@]}"; do
    if container exec "${PROJECT}-${c}" iptables -t nat -S 2>/dev/null | grep -q 'POSTROUTING.*MASQUERADE'; then
        echo "OK: ${c} NAT masquerade rule present"
    else
        echo "FAIL: ${c} NAT masquerade rule missing"
        failures=$(( failures + 1 ))
    fi
done

# MTU: every client tunnel comes up with a sane (auto-derived or fallback) MTU.
for c in "${CLIENT_NODES[@]}"; do
    mtu="$(container exec "${PROJECT}-${c}" docker exec wireguard cat /sys/class/net/wg0/mtu 2>/dev/null || echo 0)"
    if [ "${mtu}" -ge 576 ] && [ "${mtu}" -le 1500 ]; then
        echo "OK: ${c} wg0 MTU=${mtu}"
    else
        echo "FAIL: ${c} wg0 MTU invalid (${mtu})"
        failures=$(( failures + 1 ))
    fi
done

if [ "${failures}" -ne 0 ]; then
    echo "FAIL: ${failures} check(s) failed"
    exit 1
fi
echo "OK: server/client tunnels, NAT masquerade and MTU verified across all 3 pairs"
