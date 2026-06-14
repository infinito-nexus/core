#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=scripts/meta/env/load.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)/scripts/meta/env/load.sh"

# act's embedded resolver intermittently returns EAI_AGAIN.
swarm_node_dns=(--dns 1.1.1.1 --dns 8.8.8.8) # nocheck: hardcoded-dns-resolver

# /tmp:exec: Docker's default tmpfs is noexec; dpkg-buildpackage execve()s debian/rules.
for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	docker run -d --name "${node}" \
		--network "${SWARM_LAB_NETWORK}" \
		--hostname "${node}" \
		--privileged \
		--cgroupns=host \
		--security-opt seccomp=unconfined \
		--security-opt apparmor=unconfined \
		"${swarm_node_dns[@]}" \
		--tmpfs /run \
		--tmpfs /run/lock \
		--tmpfs /tmp:exec \
		-v /sys/fs/cgroup:/sys/fs/cgroup:rw \
		-v /lib/modules:/lib/modules:ro \
		jrei/systemd-ubuntu:24.04
done

SYSTEMD_TIMEOUT="${SWARM_PILOT_SYSTEMD_TIMEOUT:-180}"
for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	ready=false
	for i in $(seq 1 "${SYSTEMD_TIMEOUT}"); do
		if docker exec "${node}" systemctl is-system-running 2>/dev/null |
			grep -qE 'running|degraded|starting|maintenance'; then
			echo "systemd ready on ${node} after ${i}s"
			ready=true
			break
		fi
		sleep 1
	done
	if [ "${ready}" != "true" ]; then
		echo "FAILURE: ${node} systemd did not become responsive within ${SYSTEMD_TIMEOUT}s"
		echo "--- docker logs ${node} ---"
		docker logs "${node}" 2>&1 || true
		echo "--- last 50 journalctl lines from ${node} ---"
		docker exec "${node}" journalctl --no-pager -n 50 2>&1 || true
		echo "--- docker inspect ${node} (State) ---"
		docker inspect --format '{{json .State}}' "${node}" 2>&1 || true
		exit 1
	fi
done

HOSTS_EXTRA="$(python3 -m utils.tests.swarm.write_hosts_entries)"
for node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}"; do
	docker exec -i "${node}" sh -c 'cat >> /etc/hosts' <<<"${HOSTS_EXTRA}"
done

: "${INFINITO_DOMAIN:?Missing INFINITO_DOMAIN; source scripts/meta/env/load.sh first}"
docker exec "${MGR}" systemctl stop systemd-resolved 2>/dev/null || true
docker exec "${MGR}" systemctl mask systemd-resolved 2>/dev/null || true
docker exec "${MGR}" sh -c 'echo "nameserver 1.1.1.1" > /etc/resolv.conf' # nocheck: hardcoded-dns-resolver
docker exec "${MGR}" apt-get update -qq
docker exec "${MGR}" apt-get install -y -qq dnsmasq
# bind-dynamic: pick up docker0 when the Ansible-installed dockerd creates it later.
dnsmasq_conf="bind-dynamic
no-resolv
server=1.1.1.1 # nocheck: hardcoded-dns-resolver
server=8.8.8.8 # nocheck: hardcoded-dns-resolver
address=/${INFINITO_DOMAIN}/127.0.0.1"
docker exec -i "${MGR}" sh -c 'cat > /etc/dnsmasq.d/infinito.conf' <<<"${dnsmasq_conf}"
docker exec "${MGR}" systemctl enable --now dnsmasq
docker exec "${MGR}" sh -c 'echo "nameserver 127.0.0.1" > /etc/resolv.conf'
docker exec "${MGR}" sh -c "
	for i in \$(seq 1 30); do
		getent ahosts ${INFINITO_DOMAIN} 2>/dev/null | head -1 | grep -q '^127\.0\.0\.1 ' && exit 0
		sleep 1
	done
	echo 'FAILURE: dnsmasq did not resolve ${INFINITO_DOMAIN} to 127.0.0.1 after 30s' >&2
	exit 1
"

# Daemon DNS for containers spawned by the inner daemon; outer --dns is
# clobbered by systemd-resolved inside DinD.
# bip pins mgr-01's docker0 to the known IP so DinD-spawned containers
# reach dnsmasq via the inner bridge gateway 172.17.0.1.
# nocheck: hardcoded-dns-resolver
mgr_daemon_dns_json='{"dns": ["1.1.1.1", "8.8.8.8"], "bip": "172.17.0.1/16"}'
docker exec "${MGR}" mkdir -p /etc/docker
docker exec -i "${MGR}" sh -c 'cat > /etc/docker/daemon.json' <<<"${mgr_daemon_dns_json}"

# nocheck: hardcoded-dns-resolver
swarm_daemon_dns_json='{"dns": ["1.1.1.1", "8.8.8.8"]}'
for node in "${WRK1}" "${WRK2}"; do
	docker exec "${node}" mkdir -p /etc/docker
	docker exec -i "${node}" sh -c 'cat > /etc/docker/daemon.json' <<<"${swarm_daemon_dns_json}"
done
