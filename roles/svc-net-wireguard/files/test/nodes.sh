#!/usr/bin/env bash
# Shared definitions for the WireGuard deploy-driven e2e harness.
# shellcheck disable=SC2034
PROJECT="wg-e2e"
WGNET="${PROJECT}_net"
WG_PORT="${WIREGUARD_E2E_PORT:-51821}"
TUN_PREFIX="${WIREGUARD_E2E_TUNNEL_PREFIX:-10.13.13}"
INV_DIR="/opt/src/infinito/inventories/wg-e2e"
REPO_DIR="${WIREGUARD_E2E_REPO_DIR:-/opt/src/infinito}"

# In-node snippet: resolve the venv python make install created. load.sh's PYTHON
# resolver falls back to the system python3 (no install deps) when it can't confirm
# the venv, so pin the path explicitly and fail loudly if it is missing.
# shellcheck disable=SC2016  # $PY/$HOME must stay literal; evaluated in the node shell
NODE_VENV_PY='PY="$(ls -1 /opt/venvs/*/bin/python /root/.venvs/*/bin/python "$HOME"/.venvs/*/bin/python 2>/dev/null | head -n1)"; [ -x "$PY" ] || { echo "FAIL: no infinito venv python; candidates:" >&2; ls -ld /opt/venvs/* /root/.venvs/* "$HOME"/.venvs/* 2>/dev/null >&2; grep -iE "venv" /opt/src/infinito/.env >&2 || true; exit 1; }'

# Fresh systemd bases (Infinito's own pkgmgr parents): no infinito baked, so each
# node runs its own `make install`, and systemd can start docker.service like a
# real host. manjaro tracks Arch upstream; pkgmgr exposes it as 'arch'.
NODE_NAMES=(server1 server2 server3 wsarch wsdebian wscentos)
# Pinned image versions (never a moving tag like stable/latest): 1.15.2 is the
# digest stable currently resolves to. Bump deliberately.
NODE_IMAGES=(
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-debian:1.15.2}"
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-debian:1.15.2}"
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-debian:1.15.2}"
    "${WIREGUARD_E2E_ARCH_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-arch:1.15.2}"
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-debian:1.15.2}"
    "${WIREGUARD_E2E_CENTOS_IMAGE:-ghcr.io/kevinveenbirkenbach/pkgmgr-centos:1.15.2}"
)
NODE_OCTET=(11 12 13 14 15 16)
NODE_DISTRO=(debian debian debian arch debian centos)
