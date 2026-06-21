#!/usr/bin/env bash
# Per node: provision a dedicated inventory and render a full-mesh wg0.conf into it.
set -euo pipefail
: "${WIREGUARD_IMAGE:?}"
: "${WIREGUARD_VERSION:?}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=roles/svc-net-wireguard/files/test/nodes.sh
. "${DIR}/nodes.sh"

WG_IMAGE="${WIREGUARD_IMAGE}:${WIREGUARD_VERSION}"
WORK="/tmp/wg-e2e-keys"
mkdir -p "${WORK}"

for n in "${NODE_NAMES[@]}"; do
    priv="$(container run --rm --entrypoint wg "${WG_IMAGE}" genkey)"
    pub="$(printf '%s' "${priv}" | container run --rm -i --entrypoint sh "${WG_IMAGE}" -c 'wg pubkey')"
    printf '%s' "${priv}" > "${WORK}/${n}.priv"
    printf '%s' "${pub}" > "${WORK}/${n}.pub"
done

i=0
for n in "${NODE_NAMES[@]}"; do
    cn="${PROJECT}-${n}"
    timeout 600 container exec "${cn}" \
        bash -c "cd /opt/src/infinito && . scripts/meta/env/load.sh; ${NODE_VENV_PY}; \"\$PY\" -m cli administration inventory provision ${INV_DIR} --host ${cn} --include svc-net-wireguard" </dev/null

    self_ip="${TUN_PREFIX}.${NODE_OCTET[$i]}"
    conf="[Interface]
PrivateKey = $(cat "${WORK}/${n}.priv")
Address = ${self_ip}/24
ListenPort = 51820
"
    j=0
    for m in "${NODE_NAMES[@]}"; do
        if [ "${m}" != "${n}" ]; then
            # The wireguard container runs in the peer node's inner dockerd and
            # cannot resolve outer node names, so address the peer by its WGNET IP
            # (reached via the node's published relay port).
            ep_ip="$(container inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "${PROJECT}-${m}")"
            conf="${conf}
[Peer]
PublicKey = $(cat "${WORK}/${m}.pub")
AllowedIPs = ${TUN_PREFIX}.${NODE_OCTET[$j]}/32
Endpoint = ${ep_ip}:${WG_PORT}
PersistentKeepalive = 25
"
        fi
        j=$(( j + 1 ))
    done

    container exec "${cn}" sh -c "mkdir -p ${INV_DIR}/files/${cn}/wireguard"
    printf '%s' "${conf}" | container exec -i "${cn}" sh -c "cat > ${INV_DIR}/files/${cn}/wireguard/wg0.conf"
    echo "OK: ${n} inventory provisioned + full-mesh conf rendered"
    i=$(( i + 1 ))
done

echo "OK: all inventories registered"
