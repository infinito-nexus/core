#!/usr/bin/env bash
# Install a host role inside its pkgmgr distro container against localhost.
# Env: GUIDE_ROLE, GUIDE_RUNTIME_IMAGE.
set -euo pipefail

# Exception: strip the clone/cd lines because the checkout is already
# mounted; running them would clone a fresh tree and lose the CI changes.
awk '/^### Production$/{p=1} p && /^```bash$/{c=1; next} c && /^```$/{exit} c' \
	"roles/${GUIDE_ROLE}/README.md" |
	grep -vE '^git clone |^cd core$' >/tmp/host-deploy.sh
test -s /tmp/host-deploy.sh
docker pull "${GUIDE_RUNTIME_IMAGE}"

# Exception: boot systemd as PID 1 because the host role manages user
# timers/units; enable-linger below gives root a --user manager.
CID="$(docker run -d --privileged --cgroupns=host \
	-v /sys/fs/cgroup:/sys/fs/cgroup:rw \
	--tmpfs /run --tmpfs /run/lock \
	-v "${PWD}:${PWD}" \
	--entrypoint /sbin/init \
	"${GUIDE_RUNTIME_IMAGE}")"
trap 'docker rm -f "${CID}" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 40); do
	state="$(docker exec "${CID}" systemctl is-system-running 2>/dev/null || true)"
	case "${state}" in running | degraded) break ;; esac
	sleep 3
done
docker exec "${CID}" systemctl is-system-running 2>/dev/null | grep -qE 'running|degraded'
docker exec "${CID}" bash -lc 'loginctl enable-linger root && systemctl start user@0.service'
docker exec -i -w "${PWD}" "${CID}" bash -s </tmp/host-deploy.sh
