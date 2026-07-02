#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=scripts/meta/env/load.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)/scripts/meta/env/load.sh"

# act's embedded resolver intermittently returns EAI_AGAIN.
swarm_node_dns=(--dns 1.1.1.1 --dns 8.8.8.8) # nocheck: hardcoded-dns-resolver

pull_attempts=3
for attempt in $(seq 1 "${pull_attempts}"); do
	docker pull jrei/systemd-ubuntu:24.04 && break
	if [ "${attempt}" -eq "${pull_attempts}" ]; then
		echo "FAILURE: docker pull jrei/systemd-ubuntu:24.04 failed after ${pull_attempts} attempts" >&2
		exit 1
	fi
	sleep $((attempt * 5))
done

for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	docker run -d --name "${node}" \
		--label "${INFINITO_SWARM_TEST_LABEL}" \
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
for node in "${MGR}" "${NFS_SERVER}"; do
	docker exec -i "${node}" sh -c 'cat >> /etc/hosts' <<<"${HOSTS_EXTRA}"
done

: "${INFINITO_DOMAIN:?Missing INFINITO_DOMAIN; source scripts/meta/env/load.sh first}"
docker exec "${MGR}" systemctl stop systemd-resolved 2>/dev/null || true
docker exec "${MGR}" systemctl mask systemd-resolved 2>/dev/null || true
docker exec "${MGR}" sh -c 'echo "nameserver 1.1.1.1" > /etc/resolv.conf' # nocheck: hardcoded-dns-resolver
docker exec "${MGR}" apt-get update -qq
docker exec "${MGR}" apt-get install -y -qq dnsmasq
dnsmasq_conf="bind-dynamic
no-resolv
server=/${MGR}/${WRK1}/${WRK2}/${NFS_SERVER}/127.0.0.11 # nocheck: hardcoded-dns-resolver
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

MGR_IP=$(docker inspect "${MGR}" \
	--format "{{(index .NetworkSettings.Networks \"${SWARM_LAB_NETWORK}\").IPAddress}}")
: "${MGR_IP:?Failed to capture ${MGR} IP on ${SWARM_LAB_NETWORK}}"
wrk_dnsmasq_conf="bind-dynamic
no-resolv
server=/${MGR}/${WRK1}/${WRK2}/${NFS_SERVER}/127.0.0.11 # nocheck: hardcoded-dns-resolver
server=1.1.1.1 # nocheck: hardcoded-dns-resolver
server=8.8.8.8 # nocheck: hardcoded-dns-resolver
address=/${INFINITO_DOMAIN}/${MGR_IP}"
for node in "${WRK1}" "${WRK2}"; do
	docker exec "${node}" systemctl stop systemd-resolved 2>/dev/null || true
	docker exec "${node}" systemctl mask systemd-resolved 2>/dev/null || true
	docker exec "${node}" sh -c 'echo "nameserver 1.1.1.1" > /etc/resolv.conf' # nocheck: hardcoded-dns-resolver
	docker exec "${node}" apt-get update -qq
	docker exec "${node}" apt-get install -y -qq dnsmasq
	docker exec -i "${node}" sh -c 'cat > /etc/dnsmasq.d/infinito.conf' <<<"${wrk_dnsmasq_conf}"
	docker exec "${node}" systemctl enable --now dnsmasq
	docker exec "${node}" sh -c 'echo "nameserver 127.0.0.1" > /etc/resolv.conf'
	docker exec "${node}" sh -c "
		for i in \$(seq 1 30); do
			getent ahosts test.${INFINITO_DOMAIN} 2>/dev/null | head -1 | grep -qF '${MGR_IP} ' && exit 0
			sleep 1
		done
		echo 'FAILURE: dnsmasq on ${node} did not resolve test.${INFINITO_DOMAIN} to ${MGR_IP} after 30s' >&2
		exit 1
	"
done

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
