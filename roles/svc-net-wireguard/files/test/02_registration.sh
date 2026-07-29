#!/usr/bin/env bash
# Provision each node's inventory, deploy the 3 servers in [server] flavor, and
# turn each server's generated peer config into its paired client's wg0.conf.
# nocheck: raw-docker  # nested docker exec to read the server's generated peer conf
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=roles/svc-net-wireguard/files/test/nodes.sh
. "${DIR}/nodes.sh"

# 1) Provision a dedicated inventory on every node.
for n in "${NODE_NAMES[@]}"; do
    cn="${PROJECT}-${n}"
    timeout 600 container exec "${cn}" \
        bash -c "cd /opt/src/infinito && . scripts/meta/env/load.sh; ${NODE_VENV_PY}; \"\$PY\" -m cli administration inventory provision ${INV_DIR} --host ${cn} --include svc-net-wireguard" </dev/null
    echo "OK: ${n} inventory provisioned"
done

# 2) Deploy the servers ([server] flavor). SERVERURL=node IP makes the generated
#    peer Endpoint reachable; AllowedIPs are scoped to the wg subnet.
for s in "${SERVER_NODES[@]}"; do
    cn="${PROJECT}-${s}"
    sip="$(container inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "${cn}")"
    timeout 1800 container exec "${cn}" \
        bash -c "cd /opt/src/infinito && . scripts/meta/env/load.sh; ${NODE_VENV_PY}; \"\$PY\" -m cli administration deploy dedicated ${INV_DIR}/devices.yml --id svc-net-wireguard --password-file ${INV_DIR}/.password -e ansible_connection=local -e DOCKER_IN_CONTAINER=true -e SYS_SVC_CONTAINER_STORAGE_DRIVER=vfs -e WIREGUARD_SERVER_URL=${sip} -e WIREGUARD_SERVER_ALLOWED_IPS=${WG_SUBNET}" </dev/null
    echo "OK: ${s} deployed (server flavor, url=${sip})"
done

# 3) Extract each server's generated peer config and install it as the paired
#    client's inventory wg0.conf (its Endpoint already points at the server IP).
i=0
for s in "${SERVER_NODES[@]}"; do
    scn="${PROJECT}-${s}"
    c="${CLIENT_NODES[$i]}"
    ccn="${PROJECT}-${c}"
    peer_conf=""
    deadline=$(( $(date +%s) + 120 ))
    while true; do
        peer_conf="$(container exec "${scn}" docker exec wireguard sh -c 'cat /config/peer1/peer1.conf 2>/dev/null' 2>/dev/null || true)"
        [ -n "${peer_conf}" ] && break
        if [ "$(date +%s)" -ge "${deadline}" ]; then
            echo "FAIL: ${s} did not generate /config/peer1/peer1.conf"
            container exec "${scn}" docker exec wireguard sh -c 'ls -la /config /config/peer1 2>&1' || true
            exit 1
        fi
        sleep 3
    done
    # Drop the DNS line (no resolvconf in the client) + add a NAT keepalive.
    peer_conf="$(printf '%s\n' "${peer_conf}" | grep -v '^DNS')
PersistentKeepalive = 25"
    container exec "${ccn}" sh -c "mkdir -p ${INV_DIR}/files/${ccn}/wireguard"
    printf '%s' "${peer_conf}" | container exec -i "${ccn}" sh -c "cat > ${INV_DIR}/files/${ccn}/wireguard/wg0.conf"
    echo "OK: ${c} client config installed from ${s} peer1"
    i=$(( i + 1 ))
done

echo "OK: servers deployed, client configs registered"
