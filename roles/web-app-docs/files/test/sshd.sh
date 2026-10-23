#!/bin/sh
# shellcheck shell=sh
#
# Env:
#   DOCS_TEST_REPLAY_PUBKEY  public half of the replay key pair, authorized for root

set -e

: "${DOCS_TEST_REPLAY_PUBKEY:?}"

install_sshd() {
	if command -v sshd >/dev/null 2>&1; then
		return 0
	fi

	if command -v apt-get >/dev/null 2>&1; then
		apt-get update
		DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssh-server
		rm -rf /var/lib/apt/lists/*
	elif command -v dnf >/dev/null 2>&1; then
		dnf install -y openssh-server
		dnf clean all
	elif command -v pacman >/dev/null 2>&1; then
		pacman -Sy --noconfirm --needed openssh
		rm -rf /var/cache/pacman/pkg/*
	else
		echo "no supported package manager to install an ssh server with" >&2
		exit 1
	fi

	if ! command -v sshd >/dev/null 2>&1; then
		echo "the ssh server install left no sshd on PATH" >&2
		exit 1
	fi
}

install_sshd
ssh-keygen -A

mkdir -p /root/.ssh
chmod 700 /root/.ssh
printf '%s\n' "${DOCS_TEST_REPLAY_PUBKEY}" >/root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

mkdir -p /etc/ssh/sshd_config.d
printf 'PermitRootLogin prohibit-password\nPubkeyAuthentication yes\n' >/etc/ssh/sshd_config.d/00-docs-replay.conf
grep -q '^Include /etc/ssh/sshd_config.d/\*.conf' /etc/ssh/sshd_config ||
	sed -i '1i Include /etc/ssh/sshd_config.d/*.conf' /etc/ssh/sshd_config

systemctl enable --now ssh.service 2>/dev/null || systemctl enable --now sshd.service
