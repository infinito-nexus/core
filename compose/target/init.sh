#!/bin/sh
# shellcheck shell=sh

set -e

APT_OPTS="-o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30"
HOST_KEYS_UNIT=target-host-keys.service
SSHD_DROP_IN=/etc/ssh/sshd_config.d/00-target.conf

mask_units_that_escape_the_container() {
	systemctl mask getty.target console-getty.service getty-static.service getty@.service tmp.mount systemd-sysctl.service
}

apt_install() {
	# shellcheck disable=SC2086
	apt-get $APT_OPTS update
	# shellcheck disable=SC2086
	DEBIAN_FRONTEND=noninteractive apt-get $APT_OPTS install -y --no-install-recommends "$@"
	rm -rf /var/lib/apt/lists/*
}

install_init() {
	[ -e /sbin/init ] && return 0

	if command -v apt-get >/dev/null 2>&1; then
		apt_install systemd systemd-sysv libnss-myhostname
	elif command -v dnf >/dev/null 2>&1; then
		dnf install -y systemd
		dnf clean all
	elif command -v pacman >/dev/null 2>&1; then
		pacman -Sy --noconfirm --needed archlinux-keyring
		pacman -Syu --noconfirm --needed systemd
		rm -rf /var/cache/pacman/pkg/*
	else
		echo "no supported package manager to install an init with" >&2
		exit 1
	fi

	grep -q myhostname /etc/nsswitch.conf || sed -i "s/^hosts:.*/& myhostname/" /etc/nsswitch.conf
	[ -e /sbin/init ] || ln -sf /lib/systemd/systemd /sbin/init
}

install_sshd() {
	if command -v sshd >/dev/null 2>&1; then
		return 0
	fi

	if command -v apt-get >/dev/null 2>&1; then
		apt_install openssh-server
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

configure_sshd() {
	rm -f /etc/ssh/ssh_host_*

	mkdir -p /etc/ssh/sshd_config.d
	printf 'PermitRootLogin prohibit-password\nPubkeyAuthentication yes\n' >"${SSHD_DROP_IN}"
	grep -q '^Include /etc/ssh/sshd_config.d/\*.conf' /etc/ssh/sshd_config ||
		sed -i '1i Include /etc/ssh/sshd_config.d/*.conf' /etc/ssh/sshd_config

	printf '%s\n' \
		'[Unit]' \
		'Description=SSH host keys of this target container' \
		'Before=ssh.service sshd.service' \
		'' \
		'[Service]' \
		'Type=oneshot' \
		'ExecStart=/usr/bin/ssh-keygen -A' \
		'' \
		'[Install]' \
		'WantedBy=multi-user.target' >"/etc/systemd/system/${HOST_KEYS_UNIT}"
	systemctl enable "${HOST_KEYS_UNIT}"
}

enable_sshd() {
	if [ -e /usr/lib/systemd/system/ssh.socket ] || [ -e /lib/systemd/system/ssh.socket ]; then
		systemctl disable ssh.socket
	fi
	systemctl enable ssh.service 2>/dev/null || systemctl enable sshd.service
}

install_init
install_sshd
configure_sshd
enable_sshd
mask_units_that_escape_the_container
