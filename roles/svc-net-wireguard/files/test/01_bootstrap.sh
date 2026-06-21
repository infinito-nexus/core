#!/usr/bin/env bash
# Boot 6 fresh nodes (pkgmgr bases: 3 debian servers + arch/debian/centos
# workstations), run a full per-node `make install` in each (which also pulls in
# systemd), then re-create every node as a systemd-PID1 container from its
# installed filesystem -> the deploy can install + start docker.service exactly
# like a real host, while each node is still a freshly-installed environment.
# nocheck: raw-docker  # commit/run/logs against the DinD nodes
set -euo pipefail
: "${WIREGUARD_E2E_TIMEOUT:?}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=roles/svc-net-wireguard/files/test/nodes.sh
. "${DIR}/nodes.sh"

container network create "${WGNET}" >/dev/null 2>&1 || true

# Phase 1: boot the bare bases (no systemd yet) just to run the install in them.
i=0
for n in "${NODE_NAMES[@]}"; do
    cn="${PROJECT}-${n}"
    container rm -f "${cn}" >/dev/null 2>&1 || true
    container run -d --name "${cn}" --hostname "${cn}" --network "${WGNET}" \
        --entrypoint=sleep \
        -v "${REPO_DIR}:/opt/src/infinito-src:ro" \
        "${NODE_IMAGES[$i]}" infinity >/dev/null
    echo "OK: ${n} base booted (${NODE_IMAGES[$i]})"
    i=$(( i + 1 ))
done

# Bases ship no make/git/python and no systemd; install the bootstrap
# prerequisites first. systemd (+ the sysv-compat that provides /sbin/init) lets
# the node be re-created as a systemd PID 1 below.
install_prereqs() {
    local cn="$1" distro="$2"
    case "${distro}" in
        debian)
            timeout 600 container exec "${cn}" sh -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y make git python3 python3-venv python3-pip sudo curl ca-certificates tar gnupg systemd systemd-sysv' </dev/null ;;
        arch)
            timeout 600 container exec "${cn}" sh -c 'pacman -Sy --noconfirm make git python python-pip sudo curl ca-certificates tar gnupg systemd systemd-sysvcompat' </dev/null ;;
        centos)
            timeout 600 container exec "${cn}" sh -c 'dnf -y --allowerasing install make git python3 python3-pip sudo curl ca-certificates tar gnupg2 systemd' </dev/null ;;
    esac
}

# Phase 2: per-node install into its own copy, then re-create as a systemd node.
i=0
for n in "${NODE_NAMES[@]}"; do
    cn="${PROJECT}-${n}"
    install_prereqs "${cn}" "${NODE_DISTRO[$i]}"
    # Node-local repo copy (excluding .git): the bind-mount is shared+read-only, so
    # make install state must not leak across nodes.
    container exec "${cn}" \
        sh -c 'mkdir -p /opt/src/infinito && tar -C /opt/src/infinito-src --exclude=./.git -cf - . | tar -C /opt/src/infinito -xf -' </dev/null
    timeout 1200 container exec "${cn}" \
        sh -c 'export DEBIAN_FRONTEND=noninteractive CI=true; cd /opt/src/infinito && make install' </dev/null
    # make install pulled in systemd. Mask container-hostile first-boot units and
    # seed a machine-id so systemd reaches a ready state once it is PID 1.
    container exec "${cn}" \
        sh -c 'ln -sf /dev/null /etc/systemd/system/systemd-firstboot.service; ln -sf /dev/null /etc/systemd/system/first-boot-complete.target; : > /etc/machine-id' </dev/null
    container commit "${cn}" "wg-e2e-img-${n}" >/dev/null
    container rm -f "${cn}" >/dev/null
    # Re-create as systemd PID 1: host cgroup ns + writable cgroupfs + tmpfs /run;
    # --privileged lets the node run its own dockerd (DinD). container=docker makes
    # Infinito's DOCKER_IN_CONTAINER autodetect true.
    container run -d --name "${cn}" --hostname "${cn}" --network "${WGNET}" \
        --privileged --cgroupns=host \
        --tmpfs /run --tmpfs /run/lock \
        -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
        -e container=docker \
        --entrypoint=/sbin/init \
        "wg-e2e-img-${n}" >/dev/null
    echo "OK: ${n} make install complete + re-created as systemd node"
    i=$(( i + 1 ))
done

# Phase 3: wait until systemd has finished booting in every node (running or
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

echo "OK: all nodes bootstrapped"
