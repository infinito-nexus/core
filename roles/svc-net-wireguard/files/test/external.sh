#!/usr/bin/env bash
# Register each server's generated peer on a fresh client and assert a WireGuard
# handshake. Non-zero exit if any server is unreachable within the timeout.
set -euo pipefail

: "${WIREGUARD_E2E_SERVER_COUNT:?}"
: "${WIREGUARD_IMAGE:?}"
: "${WIREGUARD_VERSION:?}"
: "${WIREGUARD_E2E_TIMEOUT:?}"

PROJECT="wg-e2e"
NETWORK="${PROJECT}_default"
failures=0

cleanup() {
    for i in $(seq 1 "${WIREGUARD_E2E_SERVER_COUNT}"); do
        container rm -f "${PROJECT}-client${i}" >/dev/null 2>&1 || true
    done
}
trap cleanup EXIT

for i in $(seq 1 "${WIREGUARD_E2E_SERVER_COUNT}"); do
    server="${PROJECT}-wg${i}"
    client="${PROJECT}-client${i}"
    # Per local.sh: server i uses INTERNAL_SUBNET 10.13.<12+i>.0 and takes .1.
    server_subnet="10.13.$(( 12 + i )).0/24"
    server_ip="10.13.$(( 12 + i )).1"

    # Pull the generated peer config and rewrite it for the in-DinD topology:
    #  - Endpoint -> the server's service name on the shared compose network.
    #  - AllowedIPs -> only the server's tunnel subnet (0.0.0.0/0 would route the
    #    endpoint itself through the tunnel and deadlock the handshake).
    #  - PersistentKeepalive so the client actively initiates the handshake.
    peer_conf="$(container exec "${server}" cat /config/peer1/peer1.conf 2>/dev/null || true)"
    if [ -z "${peer_conf}" ]; then
        echo "FAIL: ${server} produced no peer1 config"
        failures=$(( failures + 1 ))
        continue
    fi
    peer_conf="$(printf '%s\n' "${peer_conf}" \
        | sed -E "s#^Endpoint =.*#Endpoint = wg${i}:51820#" \
        | sed -E "s#^AllowedIPs =.*#AllowedIPs = ${server_subnet}#")"
    peer_conf="$(printf '%s\nPersistentKeepalive = 25\n' "${peer_conf}")"

    # Start an idle client (no conf yet), inject the rewritten conf, restart.
    container rm -f "${client}" >/dev/null 2>&1 || true
    container run -d --name "${client}" \
        --network "${NETWORK}" \
        --cap-add NET_ADMIN \
        --sysctl=net.ipv4.conf.all.src_valid_mark=1 \
        -e PUID=1000 -e PGID=1000 -e TZ=Etc/UTC \
        "${WIREGUARD_IMAGE}:${WIREGUARD_VERSION}" >/dev/null

    printf '%s\n' "${peer_conf}" | \
        container exec -i "${client}" sh -c 'mkdir -p /config/wg_confs && cat > /config/wg_confs/wg0.conf'
    container restart "${client}" >/dev/null

    # Poll for a handshake; actively ping the server's tunnel IP each round to
    # trigger one, bounded by the timeout.
    deadline=$(( $(date +%s) + WIREGUARD_E2E_TIMEOUT ))
    ok=0
    while true; do
        container exec "${client}" ping -c1 -W2 "${server_ip}" >/dev/null 2>&1 || true
        hs="$(container exec "${client}" wg show all latest-handshakes 2>/dev/null | awk '{print $NF}' | sort -nr | head -n1)"
        case "${hs}" in (''|*[!0-9]*) hs=0 ;; esac
        if [ "${hs}" -gt 0 ]; then
            echo "OK: handshake with ${server} (latest-handshake=${hs})"
            ok=1
            break
        fi
        if [ "$(date +%s)" -ge "${deadline}" ]; then
            echo "FAIL: no handshake with ${server} within ${WIREGUARD_E2E_TIMEOUT}s"
            break
        fi
        sleep 3
    done
    if [ "${ok}" -ne 1 ]; then
        failures=$(( failures + 1 ))
    fi
done

if [ "${failures}" -ne 0 ]; then
    echo "FAIL: ${failures} server(s) unreachable via WireGuard handshake"
    exit 1
fi
echo "OK: all ${WIREGUARD_E2E_SERVER_COUNT} servers reachable via WireGuard handshake"
