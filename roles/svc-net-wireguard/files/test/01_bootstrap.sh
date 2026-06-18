#!/usr/bin/env bash
# Boot 6 empty containers (3 debian servers + manjaro/debian/centos workstations),
# make install in each, and start an inner dockerd (DinD) so the role can deploy.
# nocheck: raw-docker  # dockerd/docker run inside the DinD nodes (no wrapper there)
set -euo pipefail
: "${WIREGUARD_E2E_TIMEOUT:?}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=roles/svc-net-wireguard/files/test/nodes.sh
. "${DIR}/nodes.sh"

container network create "${WGNET}" >/dev/null 2>&1 || true

i=0
for n in "${NODE_NAMES[@]}"; do
    cn="${PROJECT}-${n}"
    container rm -f "${cn}" >/dev/null 2>&1 || true
    container run -d --name "${cn}" --hostname "${cn}" --network "${WGNET}" \
        --privileged \
        -v "${REPO_DIR}:/opt/src/infinito" \
        "${NODE_IMAGES[$i]}" sleep infinity >/dev/null
    echo "OK: ${n} booted (${NODE_IMAGES[$i]})"
    i=$(( i + 1 ))
done

# Raw base images ship no make/git/python; install the bootstrap prerequisites
# before `make install` runs the full Infinito.Nexus install.
install_prereqs() {
    local cn="$1" distro="$2"
    case "${distro}" in
        debian)
            timeout 600 container exec "${cn}" sh -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y make git python3 python3-venv python3-pip sudo curl ca-certificates' </dev/null ;;
        manjaro)
            timeout 600 container exec "${cn}" sh -c 'pacman -Sy --noconfirm make git python python-pip sudo curl ca-certificates' </dev/null ;;
        centos)
            timeout 600 container exec "${cn}" sh -c 'dnf -y install make git python3 python3-pip sudo curl ca-certificates' </dev/null ;;
    esac
}

i=0
for n in "${NODE_NAMES[@]}"; do
    cn="${PROJECT}-${n}"
    install_prereqs "${cn}" "${NODE_DISTRO[$i]}"
    timeout 1200 container exec "${cn}" \
        sh -c 'export DEBIAN_FRONTEND=noninteractive CI=true; cd /opt/src/infinito && make install' </dev/null
    container exec -d "${cn}" sh -c 'dockerd >/tmp/dockerd.log 2>&1'
    # shellcheck disable=SC2016  # the $(...) runs inside the node, not in this shell
    container exec "${cn}" sh -c 'for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && exit 0; sleep 2; done; echo "dockerd did not come up"; exit 1'
    echo "OK: ${n} make install + dockerd ready"
    i=$(( i + 1 ))
done

echo "OK: all nodes bootstrapped"
