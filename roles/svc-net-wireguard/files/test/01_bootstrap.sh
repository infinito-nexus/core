#!/usr/bin/env bash
# Boot 6 empty containers (3 debian servers + manjaro/debian/centos workstations)
# and make install in each -> deploy-ready Infinito.Nexus environment. The Docker
# engine itself is installed + started by the deploy (sys-svc-container, DinD-aware).
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
    # container=docker makes Infinito's DOCKER_IN_CONTAINER autodetect true
    # (it keys off the `container` env var, which plain Docker does not set).
    container run -d --name "${cn}" --hostname "${cn}" --network "${WGNET}" \
        --privileged \
        -e container=docker \
        -v "${REPO_DIR}:/opt/src/infinito-src:ro" \
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
            timeout 600 container exec "${cn}" sh -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y make git python3 python3-venv python3-pip sudo curl ca-certificates tar' </dev/null ;;
        manjaro)
            timeout 600 container exec "${cn}" sh -c 'pacman -Sy --noconfirm make git python python-pip sudo curl ca-certificates tar' </dev/null ;;
        centos)
            timeout 600 container exec "${cn}" sh -c 'dnf -y --allowerasing install make git python3 python3-pip sudo curl ca-certificates tar' </dev/null ;;
    esac
}

i=0
for n in "${NODE_NAMES[@]}"; do
    cn="${PROJECT}-${n}"
    install_prereqs "${cn}" "${NODE_DISTRO[$i]}"
    # Node-local repo copy (excluding .git): the bind-mount is shared+read-only, so
    # make install state (.env, venv stamps) must not leak across nodes — otherwise
    # later nodes short-circuit the install and never create their own venv.
    container exec "${cn}" \
        sh -c 'mkdir -p /opt/src/infinito && tar -C /opt/src/infinito-src --exclude=./.git -cf - . | tar -C /opt/src/infinito -xf -' </dev/null
    timeout 1200 container exec "${cn}" \
        sh -c 'export DEBIAN_FRONTEND=noninteractive CI=true; cd /opt/src/infinito && make install' </dev/null
    echo "OK: ${n} make install complete"
    i=$(( i + 1 ))
done

echo "OK: all nodes bootstrapped"
