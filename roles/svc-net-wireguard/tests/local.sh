#!/usr/bin/env bash
# Bring up WIREGUARD_E2E_SERVER_COUNT WireGuard servers (compose, in DinD) and
# assert each is healthy. Uses the `container` / `compose` wrappers.
set -euo pipefail

: "${WIREGUARD_E2E_SERVER_COUNT:?}"
: "${WIREGUARD_IMAGE:?}"
: "${WIREGUARD_VERSION:?}"
: "${WIREGUARD_E2E_BASE_PORT:?}"
: "${WIREGUARD_E2E_WORKDIR:?}"
: "${WIREGUARD_E2E_TIMEOUT:?}"

PROJECT="wg-e2e"
WORKDIR="${WIREGUARD_E2E_WORKDIR}"
COMPOSE_FILE="${WORKDIR}/compose.yml"
mkdir -p "${WORKDIR}"

# Render a compose file with one WireGuard server service per instance.
{
    echo "services:"
    for i in $(seq 1 "${WIREGUARD_E2E_SERVER_COUNT}"); do
        port=$(( WIREGUARD_E2E_BASE_PORT + i - 1 ))
        subnet="10.13.$(( 12 + i )).0"
        cat <<SVC
  wg${i}:
    image: "${WIREGUARD_IMAGE}:${WIREGUARD_VERSION}"
    container_name: ${PROJECT}-wg${i}
    cap_add:
      - NET_ADMIN
    sysctls:
      - net.ipv4.conf.all.src_valid_mark=1
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Etc/UTC
      - SERVERPORT=${port}
      - PEERS=1
      - PEERDNS=auto
      - INTERNAL_SUBNET=${subnet}
    ports:
      - "${port}:51820/udp"
    volumes:
      - "wg${i}_config:/config"
    healthcheck:
      test: ["CMD-SHELL", "wg show | grep -q interface || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 20
SVC
    done
    echo "volumes:"
    for i in $(seq 1 "${WIREGUARD_E2E_SERVER_COUNT}"); do
        echo "  wg${i}_config:"
    done
} > "${COMPOSE_FILE}"

echo "OK: rendered ${COMPOSE_FILE} (${WIREGUARD_E2E_SERVER_COUNT} servers)"

compose --chdir "${WORKDIR}" --project "${PROJECT}" up -d

# Wait until every server container reports healthy, bounded by the timeout.
deadline=$(( $(date +%s) + WIREGUARD_E2E_TIMEOUT ))
for i in $(seq 1 "${WIREGUARD_E2E_SERVER_COUNT}"); do
    name="${PROJECT}-wg${i}"
    while true; do
        status="$(container inspect --format '{{.State.Health.Status}}' "${name}" 2>/dev/null || echo missing)"
        if [ "${status}" = "healthy" ]; then
            echo "OK: ${name} healthy"
            break
        fi
        if [ "$(date +%s)" -ge "${deadline}" ]; then
            echo "FAIL: ${name} not healthy within ${WIREGUARD_E2E_TIMEOUT}s (status=${status})"
            compose --chdir "${WORKDIR}" --project "${PROJECT}" logs "wg${i}" || true
            exit 1
        fi
        sleep 3
    done
done

echo "OK: all ${WIREGUARD_E2E_SERVER_COUNT} WireGuard servers healthy"
