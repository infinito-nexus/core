#!/usr/bin/env bash

set -euo pipefail

if command -v pacman >/dev/null 2>&1; then
	pacman -Sy --noconfirm --needed docker bind fuse-overlayfs
elif command -v apt-get >/dev/null 2>&1; then
	export DEBIAN_FRONTEND=noninteractive
	APT_TIMEOUT=10m
	APT_INSTALL_TIMEOUT=20m
	APT_OPTS=(-o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)
	timeout -k 30 "${APT_TIMEOUT}" apt-get "${APT_OPTS[@]}" update
	timeout -k 30 "${APT_INSTALL_TIMEOUT}" apt-get "${APT_OPTS[@]}" install -y --no-install-recommends docker-ce containerd.io dnsutils fuse-overlayfs
elif command -v dnf >/dev/null 2>&1; then
	dnf -y install docker-ce containerd.io bind-utils fuse-overlayfs
elif command -v yum >/dev/null 2>&1; then
	yum -y install docker-ce containerd.io bind-utils fuse-overlayfs
else
	echo "no supported package manager for docker daemon install" >&2
	exit 1
fi
