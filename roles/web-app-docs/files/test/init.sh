#!/bin/sh
# shellcheck shell=sh
#
# Installs systemd into whatever it runs in: the Dockerfile beside it RUNs it
# in a build stage, never run it on a host.
#
# No container engine here: the replayed deploy installs docker-ce itself, and a
# target that already carries the distribution's engine kills that deploy's
# docker.service restart with "failed to load listeners: no sockets found via
# socket activation".

set -e

APT_OPTS="-o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30"

mask_units_that_escape_the_container() {
	systemctl mask getty.target console-getty.service getty-static.service getty@.service tmp.mount
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

install_init
mask_units_that_escape_the_container
