#!/usr/bin/env bash
set -euo pipefail

# /tmp:exec: Docker's default tmpfs is noexec; dpkg-buildpackage execve()s debian/rules.
for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	docker run -d --name "${node}" \
		--network swarm-lab \
		--hostname "${node}" \
		--privileged \
		--tmpfs /run \
		--tmpfs /run/lock \
		--tmpfs /tmp:exec \
		-v /sys/fs/cgroup:/sys/fs/cgroup:rw \
		-v /lib/modules:/lib/modules:ro \
		jrei/systemd-ubuntu:24.04
done

for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	for i in $(seq 1 60); do
		if docker exec "${node}" systemctl is-system-running 2>/dev/null |
			grep -qE 'running|degraded|starting|maintenance'; then
			echo "systemd ready on ${node} after ${i}s"
			break
		fi
		sleep 1
	done
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
