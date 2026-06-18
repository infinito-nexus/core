#!/usr/bin/env bash
# Shared definitions for the WireGuard deploy-driven e2e harness.
# shellcheck disable=SC2034
PROJECT="wg-e2e"
WGNET="${PROJECT}_net"
WG_PORT="${WIREGUARD_E2E_PORT:-51821}"
TUN_PREFIX="${WIREGUARD_E2E_TUNNEL_PREFIX:-10.13.13}"
INV_DIR="/opt/src/infinito/inventories/wg-e2e"
REPO_DIR="${WIREGUARD_E2E_REPO_DIR:-/opt/src/infinito}"

NODE_NAMES=(server1 server2 server3 wsmanjaro wsdebian wscentos)
NODE_IMAGES=(
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-debian:latest}"
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-debian:latest}"
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-debian:latest}"
    "${WIREGUARD_E2E_MANJARO_IMAGE:-manjarolinux/base}"
    "${WIREGUARD_E2E_DEBIAN_IMAGE:-debian:latest}"
    "${WIREGUARD_E2E_CENTOS_IMAGE:-quay.io/centos/centos:stream9}"
)
NODE_OCTET=(11 12 13 14 15 16)
NODE_DISTRO=(debian debian debian manjaro debian centos)
