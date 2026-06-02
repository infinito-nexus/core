#!/usr/bin/env bash
set -euo pipefail

# /tmp:exec: Docker's default tmpfs is noexec; dpkg-buildpackage execve()s debian/rules.
for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	docker run -d --name "${node}" \
		--network swarm-lab \
		--hostname "${node}" \
		--privileged \
		--cgroupns=host \
		--security-opt seccomp=unconfined \
		--security-opt apparmor=unconfined \
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

MGR_HOSTS_EXTRA="$(
	cat <<'EOF'
127.0.0.1 infinito.localhost
127.0.0.1 admin.infinito.localhost
127.0.0.1 auth.infinito.localhost
127.0.0.1 m.wiki.infinito.localhost
127.0.0.1 wiki.infinito.localhost
127.0.0.1 mail.infinito.localhost
EOF
)"
docker exec -i "${MGR}" sh -c 'cat >> /etc/hosts' <<<"${MGR_HOSTS_EXTRA}"
