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

sed -i "s#<your-ssh-public-key>#ssh-ed25519 AAAA_TEST_DUMMY_KEY github-ci-dummy@infinito#" /tmp/host-deploy.sh

docker pull "${GUIDE_RUNTIME_IMAGE}"

# Exception: the pkgmgr base image ships no init of its own.
PREP="$(docker run -d --entrypoint sleep "${GUIDE_RUNTIME_IMAGE}" infinity)"
docker exec "${PREP}" sh -c '
	set -e
	if command -v apt-get >/dev/null 2>&1; then
		apt-get update
		DEBIAN_FRONTEND=noninteractive apt-get install -y systemd systemd-sysv libnss-myhostname
	elif command -v dnf >/dev/null 2>&1; then
		dnf install -y systemd
	elif command -v pacman >/dev/null 2>&1; then
		pacman -Sy --noconfirm systemd
	fi
	grep -q myhostname /etc/nsswitch.conf || sed -i "s/^hosts:.*/& myhostname/" /etc/nsswitch.conf
	[ -e /sbin/init ] || ln -sf /lib/systemd/systemd /sbin/init
'
BOOT_IMAGE="guide-boot:${GUIDE_ROLE}"
docker commit "${PREP}" "${BOOT_IMAGE}" >/dev/null
docker rm -f "${PREP}" >/dev/null 2>&1 || true

CID="$(docker run -d --privileged --cgroupns=host \
	-v /sys/fs/cgroup:/sys/fs/cgroup:rw \
	--tmpfs /run --tmpfs /run/lock \
	-v "${PWD}:${PWD}" \
	--entrypoint /sbin/init \
	"${BOOT_IMAGE}")"
trap 'docker rm -f "${CID}" >/dev/null 2>&1 || true; docker rmi -f "${BOOT_IMAGE}" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 40); do
	state="$(docker exec "${CID}" systemctl is-system-running 2>/dev/null || true)"
	case "${state}" in running | degraded) break ;; esac
	sleep 3
done
state="$(docker exec "${CID}" systemctl is-system-running 2>/dev/null || true)"
case "${state}" in
running | degraded) ;;
*)
	echo "systemd never reached a running state (last: ${state:-unknown})" >&2
	docker exec "${CID}" systemctl --no-pager status 2>/dev/null | head -n 20 >&2 || true
	exit 1
	;;
esac
docker exec "${CID}" bash -lc 'systemctl unmask systemd-logind && systemctl start systemd-logind && loginctl enable-linger root && systemctl start user@0.service'
docker exec -i -w "${PWD}" "${CID}" bash -s </tmp/host-deploy.sh
