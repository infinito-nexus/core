#!/usr/bin/env bash
# Shared definitions for the WireGuard deploy-driven e2e harness.
# shellcheck disable=SC2034
PROJECT="wg-e2e"
WGNET="${PROJECT}_net"
TUN_PREFIX="${WIREGUARD_E2E_TUNNEL_PREFIX:-10.13.13}"
INV_DIR="/opt/src/infinito/inventories/wg-e2e"
REPO_DIR="${WIREGUARD_E2E_REPO_DIR:-/opt/src/infinito}"

# In-node snippet: pin the make-install venv python (load.sh would silently fall
# back to the system python3, which lacks the install deps).
# shellcheck disable=SC2016  # $PY/$HOME must stay literal; evaluated in the node shell
NODE_VENV_PY='PY="$(ls -1 /opt/venvs/*/bin/python /root/.venvs/*/bin/python "$HOME"/.venvs/*/bin/python 2>/dev/null | head -n1)"; [ -x "$PY" ] || { echo "FAIL: no infinito venv python; candidates:" >&2; ls -ld /opt/venvs/* /root/.venvs/* "$HOME"/.venvs/* 2>/dev/null >&2; grep -iE "venv" /opt/src/infinito/.env >&2 || true; exit 1; }'

# Fresh systemd bases (Infinito's pkgmgr parents): no infinito baked, pinned tags
# (never moving). manjaro tracks Arch upstream; pkgmgr exposes it as 'arch'.
NODE_NAMES=(server1 server2 server3 wsarch wsdebian wscentos)
NODE_IMAGES=(
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-debian:1.15.2}"
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-debian:1.15.2}"
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-debian:1.15.2}"
    "${WIREGUARD_E2E_ARCH_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-arch:1.15.2}"
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-debian:1.15.2}"
    "${WIREGUARD_E2E_CENTOS_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-centos:1.15.2}"
)
NODE_DISTRO=(debian debian debian arch debian centos)

# Hub-spoke pairs: CLIENT_NODES[i] is a WireGuard client of SERVER_NODES[i].
SERVER_NODES=(server1 server2 server3)
CLIENT_NODES=(wsarch wsdebian wscentos)
# Workstations additionally deployed behind NAT ([client, nat] flavor).
NAT_NODES=(wsdebian)
# linuxserver server mode on INTERNAL_SUBNET=10.13.13.0: server is .1, its peer .2.
WG_SERVER_IP="${TUN_PREFIX}.1"
WG_CLIENT_IP="${TUN_PREFIX}.2"
WG_SUBNET="${TUN_PREFIX}.0/24"
