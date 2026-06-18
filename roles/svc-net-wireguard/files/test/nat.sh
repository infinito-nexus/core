#!/usr/bin/env bash
# Client-mode + NAT: a WireGuard client (MTU 1400) reaches an upstream host only
# through a gateway that masquerades tunnel traffic (the role's client NAT logic).
set -euo pipefail

: "${WIREGUARD_IMAGE:?}"
: "${WIREGUARD_VERSION:?}"
: "${WIREGUARD_E2E_TIMEOUT:?}"

WG="${WIREGUARD_IMAGE}:${WIREGUARD_VERSION}"
PROJECT="wg-e2e"
WGNET="${PROJECT}_nat_wg"
UPNET="${PROJECT}_nat_up"
GW="${PROJECT}-nat-gw"
CLIENT="${PROJECT}-nat-client"
UP="${PROJECT}-nat-up"
TUN_SUBNET="10.13.20.0/24"
GW_TUN_IP="10.13.20.1"
CLIENT_TUN_IP="10.13.20.2"
UP_SUBNET="10.30.30.0/24"
UP_IP="10.30.30.9"
MTU=1400
PORT=51820

cleanup() {
    container rm -f "${GW}" "${CLIENT}" "${UP}" >/dev/null 2>&1 || true
    container network rm "${WGNET}" "${UPNET}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

container network create "${WGNET}" >/dev/null 2>&1 || true
container network create --subnet "${UP_SUBNET}" "${UPNET}" >/dev/null 2>&1 || true

start_wg_node() {
    local cn="$1"
    container rm -f "${cn}" >/dev/null 2>&1 || true
    container run -d --name "${cn}" --network "${WGNET}" \
        --cap-add NET_ADMIN --cap-add SYS_MODULE --device=/dev/net/tun \
        --sysctl=net.ipv4.conf.all.src_valid_mark=1 \
        --sysctl=net.ipv4.ip_forward=1 \
        --entrypoint sleep "${WG}" infinity >/dev/null
    container exec "${cn}" sh -c 'apk add --no-cache iptables iputils-ping 2>/dev/null || apk add --no-cache iptables iputils'
    container exec "${cn}" sh -c 'mkdir -p /tmp/wg; umask 077; wg genkey > /tmp/wg/priv; wg pubkey < /tmp/wg/priv > /tmp/wg/pub'
}

start_wg_node "${GW}"
start_wg_node "${CLIENT}"
container network connect "${UPNET}" "${GW}" >/dev/null

container rm -f "${UP}" >/dev/null 2>&1 || true
container run -d --name "${UP}" --network "${UPNET}" --ip "${UP_IP}" \
    --entrypoint sleep "${WG}" infinity >/dev/null

gw_pub="$(container exec "${GW}" cat /tmp/wg/pub)"
client_pub="$(container exec "${CLIENT}" cat /tmp/wg/pub)"
gw_priv="$(container exec "${GW}" cat /tmp/wg/priv)"
client_priv="$(container exec "${CLIENT}" cat /tmp/wg/priv)"

printf '%s\n' "[Interface]
PrivateKey = ${gw_priv}
Address = ${GW_TUN_IP}/24
ListenPort = ${PORT}

[Peer]
PublicKey = ${client_pub}
AllowedIPs = ${CLIENT_TUN_IP}/32
" | container exec -i "${GW}" sh -c 'cat > /tmp/wg/wg0.conf'
container exec "${GW}" wg-quick up /tmp/wg/wg0.conf

printf '%s\n' "[Interface]
PrivateKey = ${client_priv}
Address = ${CLIENT_TUN_IP}/24
MTU = ${MTU}

[Peer]
PublicKey = ${gw_pub}
AllowedIPs = ${TUN_SUBNET}, ${UP_SUBNET}
Endpoint = ${GW}:${PORT}
PersistentKeepalive = 25
" | container exec -i "${CLIENT}" sh -c 'cat > /tmp/wg/wg0.conf'
container exec "${CLIENT}" wg-quick up /tmp/wg/wg0.conf

# Gateway applies the role's client NAT logic (forward tunnel traffic + masquerade).
container exec "${GW}" sh -c "iptables -A FORWARD -i wg0 -j ACCEPT && iptables -t nat -A POSTROUTING -s ${TUN_SUBNET} -j MASQUERADE"
if ! container exec "${GW}" sh -c 'iptables -t nat -S POSTROUTING | grep -q MASQUERADE'; then
    echo "FAIL: masquerade rule not present after enabling NAT"
    exit 1
fi
echo "OK: NAT masquerade rule present on gateway"

deadline=$(( $(date +%s) + WIREGUARD_E2E_TIMEOUT ))
ok=0
while true; do
    container exec "${CLIENT}" ping -c1 -W2 "${GW_TUN_IP}" >/dev/null 2>&1 || true
    hs="$(container exec "${CLIENT}" wg show all latest-handshakes 2>/dev/null | awk '{print $NF}' | sort -nr | head -n1)"
    case "${hs}" in (''|*[!0-9]*) hs=0 ;; esac
    if [ "${hs}" -gt 0 ]; then
        ok=1
        break
    fi
    if [ "$(date +%s)" -ge "${deadline}" ]; then
        break
    fi
    sleep 3
done
if [ "${ok}" -ne 1 ]; then
    echo "FAIL: client never handshook with gateway"
    exit 1
fi
echo "OK: client handshake with gateway"

mtu="$(container exec "${CLIENT}" cat /sys/class/net/wg0/mtu 2>/dev/null || echo 0)"
if [ "${mtu}" != "${MTU}" ]; then
    echo "FAIL: client wg0 MTU=${mtu}, expected ${MTU}"
    exit 1
fi
echo "OK: client tunnel MTU=${mtu}"

deadline=$(( $(date +%s) + WIREGUARD_E2E_TIMEOUT ))
ok=0
while true; do
    if container exec "${CLIENT}" ping -c1 -W2 "${UP_IP}" >/dev/null 2>&1; then
        ok=1
        break
    fi
    if [ "$(date +%s)" -ge "${deadline}" ]; then
        break
    fi
    sleep 3
done
if [ "${ok}" -ne 1 ]; then
    echo "FAIL: client could not reach upstream ${UP_IP} through NAT masquerade"
    exit 1
fi
echo "OK: client reached upstream ${UP_IP} via NAT masquerade"

# NAT disabled: remove the masquerade and confirm the rule is gone.
container exec "${GW}" sh -c "iptables -t nat -D POSTROUTING -s ${TUN_SUBNET} -j MASQUERADE"
if container exec "${GW}" sh -c 'iptables -t nat -S POSTROUTING | grep -q MASQUERADE'; then
    echo "FAIL: masquerade rule still present after disabling NAT"
    exit 1
fi
echo "OK: masquerade rule absent after disabling NAT"

echo "OK: client-mode + NAT verified"
