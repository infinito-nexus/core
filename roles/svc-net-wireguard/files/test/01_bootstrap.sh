#!/usr/bin/env bash
# Boot 6 fresh systemd nodes (3 debian servers + arch/debian/centos workstations)
# and make install in each -> deploy-ready Infinito.Nexus environment. systemd
# runs as PID 1 so the deploy can install + start docker.service like a real host.
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
    # systemd-in-container needs the host cgroup ns, a writable cgroupfs and
    # tmpfs /run; --privileged also lets the node run its own dockerd (DinD).
    # container=docker makes Infinito's DOCKER_IN_CONTAINER autodetect true. The
    # pkgmgr base entrypoint runs the pkgmgr CLI, so override it with systemd.
    container run -d --name "${cn}" --hostname "${cn}" --network "${WGNET}" \
        --privileged --cgroupns=host \
        --tmpfs /run --tmpfs /run/lock \
        -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
        -e container=docker \
        --entrypoint=/sbin/init \
        -v "${REPO_DIR}:/opt/src/infinito-src:ro" \
        "${NODE_IMAGES[$i]}" >/dev/null
    echo "OK: ${n} booted (${NODE_IMAGES[$i]})"
    i=$(( i + 1 ))
done

# Wait for systemd to finish booting before installing/deploying (running or
# degraded both mean PID 1 is up; some units legitimately fail in a container).
for n in "${NODE_NAMES[@]}"; do
    cn="${PROJECT}-${n}"
    deadline=$(( $(date +%s) + 120 ))
    while true; do
        # is-system-running exits non-zero on 'degraded'; capture to dodge pipefail.
        state="$(container exec "${cn}" systemctl is-system-running 2>/dev/null || true)"
        case "${state}" in
            *running*|*degraded*) break ;;
        esac
        if [ "$(date +%s)" -ge "${deadline}" ]; then
            echo "FAIL: systemd did not become ready in ${n} (state=${state})"
            container exec "${cn}" sh -c 'cat /proc/1/comm; ls -l /sbin/init' 2>&1 || true
            container logs "${cn}" 2>&1 | tail -n 20 || true
            exit 1
        fi
        sleep 2
    done
    echo "OK: ${n} systemd ready"
done

# Install the bootstrap prerequisites before `make install` runs the full install.
install_prereqs() {
    local cn="$1" distro="$2"
    case "${distro}" in
        debian)
            timeout 600 container exec "${cn}" sh -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y make git python3 python3-venv python3-pip sudo curl ca-certificates tar gnupg' </dev/null ;;
        arch)
            timeout 600 container exec "${cn}" sh -c 'pacman -Sy --noconfirm make git python python-pip sudo curl ca-certificates tar gnupg' </dev/null ;;
        centos)
            timeout 600 container exec "${cn}" sh -c 'dnf -y --allowerasing install make git python3 python3-pip sudo curl ca-certificates tar gnupg2' </dev/null ;;
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
