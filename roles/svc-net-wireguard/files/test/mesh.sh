#!/usr/bin/env bash
# Full-mesh DinD test across ALL nodes: 3 servers (role image) + 3 distro client
# workstations (CentOS / Debian / Manjaro). Every node is peered directly to the
# other five. Asserts a WireGuard handshake on every link (5 peers per node) and
# ICMP ping reachability across every node pair.
set -euo pipefail

: "${WIREGUARD_IMAGE:?}"
: "${WIREGUARD_VERSION:?}"
: "${WIREGUARD_E2E_TIMEOUT:?}"

PROJECT="wg-e2e"
NETWORK="${PROJECT}_mesh"
PORT=51820
WG="${WIREGUARD_IMAGE}:${WIREGUARD_VERSION}"

names=(server1 server2 server3 centos debian manjaro)
images=("${WG}" "${WG}" "${WG}"
        "${WIREGUARD_E2E_CENTOS_IMAGE:-quay.io/centos/centos:stream9}"
        "${WIREGUARD_E2E_DEBIAN_IMAGE:-debian:bookworm}"
        "${WIREGUARD_E2E_MANJARO_IMAGE:-manjarolinux/base}")
kinds=(server server server centos debian manjaro)
ips=(10.20.20.1 10.20.20.2 10.20.20.3 10.20.20.4 10.20.20.5 10.20.20.6)

cleanup() {
    for n in "${names[@]}"; do
        container rm -f "${PROJECT}-${n}" >/dev/null 2>&1 || true
    done
    container network rm "${NETWORK}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

container network create "${NETWORK}" >/dev/null 2>&1 || true

ip_of() {
    local want="$1" i=0
    for n in "${names[@]}"; do
        if [ "${n}" = "${want}" ]; then
            echo "${ips[$i]}"
            return 0
        fi
        i=$(( i + 1 ))
    done
}

# The role image (linuxserver) ships wg/wg-quick and only needs ping; the distro
# clients install wireguard-tools with their own package manager.
install_deps() {
    local cn="$1" kind="$2"
    case "${kind}" in
        server)
            container exec "${cn}" sh -c 'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y iputils-ping' ;;
        centos)
            container exec "${cn}" sh -c 'dnf -y install epel-release && dnf -y install wireguard-tools iproute iputils' ;;
        debian)
            container exec "${cn}" sh -c 'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y wireguard-tools iproute2 iputils-ping' ;;
        manjaro)
            container exec "${cn}" sh -c 'pacman -Sy --noconfirm archlinux-keyring && pacman -S --noconfirm wireguard-tools iproute2 iputils' ;;
    esac
}

# 1. Start every node and install dependencies.
i=0
for n in "${names[@]}"; do
    cn="${PROJECT}-${n}"
    container rm -f "${cn}" >/dev/null 2>&1 || true
    if [ "${kinds[$i]}" = "server" ]; then
        container run -d --name "${cn}" --network "${NETWORK}" \
            --cap-add NET_ADMIN --cap-add SYS_MODULE --device=/dev/net/tun \
            --entrypoint sleep "${images[$i]}" infinity >/dev/null
    else
        container run -d --name "${cn}" --network "${NETWORK}" \
            --cap-add NET_ADMIN --cap-add SYS_MODULE --device=/dev/net/tun \
            "${images[$i]}" sleep infinity >/dev/null
    fi
    i=$(( i + 1 ))
done
i=0
for n in "${names[@]}"; do
    install_deps "${PROJECT}-${n}" "${kinds[$i]}"
    echo "OK: deps ready on ${n} (${kinds[$i]})"
    i=$(( i + 1 ))
done

# 2. Generate a keypair on each node; collect public keys.
declare -A pub
for n in "${names[@]}"; do
    cn="${PROJECT}-${n}"
    container exec "${cn}" sh -c 'mkdir -p /etc/wireguard; umask 077; wg genkey > /etc/wireguard/priv; wg pubkey < /etc/wireguard/priv > /etc/wireguard/pub'
    pub[${n}]="$(container exec "${cn}" cat /etc/wireguard/pub)"
done

# 3. Render a full-mesh wg0.conf per node (the other five as direct peers) and bring it up.
i=0
for n in "${names[@]}"; do
    cn="${PROJECT}-${n}"
    priv="$(container exec "${cn}" cat /etc/wireguard/priv)"
    conf="[Interface]
PrivateKey = ${priv}
Address = ${ips[$i]}/24
ListenPort = ${PORT}
"
    for m in "${names[@]}"; do
        if [ "${m}" != "${n}" ]; then
            conf="${conf}
[Peer]
PublicKey = ${pub[${m}]}
AllowedIPs = $(ip_of "${m}")/32
Endpoint = ${PROJECT}-${m}:${PORT}
PersistentKeepalive = 25
"
        fi
    done
    printf '%s' "${conf}" | container exec -i "${cn}" sh -c 'cat > /etc/wireguard/wg0.conf'
    container exec "${cn}" wg-quick up wg0
    echo "OK: ${n} tunnel up (${ips[$i]})"
    i=$(( i + 1 ))
done

# 4. Verify ICMP reachability across every node pair, bounded by the timeout.
deadline=$(( $(date +%s) + WIREGUARD_E2E_TIMEOUT ))
failures=0
for n in "${names[@]}"; do
    cn="${PROJECT}-${n}"
    for m in "${names[@]}"; do
        if [ "${m}" = "${n}" ]; then
            continue
        fi
        target="$(ip_of "${m}")"
        ok=0
        while true; do
            if container exec "${cn}" ping -c1 -W2 "${target}" >/dev/null 2>&1; then
                echo "OK: ${n} -> ${m} (${target}) reachable over tunnel"
                ok=1
                break
            fi
            if [ "$(date +%s)" -ge "${deadline}" ]; then
                echo "FAIL: ${n} cannot reach ${m} (${target}) within ${WIREGUARD_E2E_TIMEOUT}s"
                break
            fi
            sleep 3
        done
        if [ "${ok}" -ne 1 ]; then
            failures=$(( failures + 1 ))
        fi
    done
done

# 5. Assert every node established a handshake with all five peers.
peers_expected=$(( ${#names[@]} - 1 ))
for n in "${names[@]}"; do
    cn="${PROJECT}-${n}"
    hs="$(container exec "${cn}" wg show wg0 latest-handshakes | awk '$2 != "" && $2 != "0"' | wc -l | tr -d ' ')"
    echo "OK: ${n} has ${hs}/${peers_expected} peer handshake(s)"
    if [ "${hs}" -lt "${peers_expected}" ]; then
        echo "FAIL: ${n} expected ${peers_expected} peer handshakes, got ${hs}"
        failures=$(( failures + 1 ))
    fi
done

if [ "${failures}" -ne 0 ]; then
    echo "FAIL: ${failures} mesh check(s) failed"
    exit 1
fi
echo "OK: full-mesh connectivity verified across all servers + clients (${#names[@]} nodes)"
