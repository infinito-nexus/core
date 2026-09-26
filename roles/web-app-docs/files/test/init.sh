#!/bin/sh
# shellcheck shell=sh
#
# Installs systemd into whatever it runs in: the Dockerfile beside it RUNs it
# in a build stage, never run it on a host.

set -e

[ -e /sbin/init ] && exit 0

APT_OPTS="-o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30"

if command -v apt-get >/dev/null 2>&1; then
	# shellcheck disable=SC2086
	apt-get $APT_OPTS update
	# shellcheck disable=SC2086
	DEBIAN_FRONTEND=noninteractive apt-get $APT_OPTS install -y --no-install-recommends \
		systemd systemd-sysv libnss-myhostname
	rm -rf /var/lib/apt/lists/*
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
