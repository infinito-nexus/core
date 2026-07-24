#!/usr/bin/env bash

set -euo pipefail

if command -v pacman >/dev/null 2>&1; then
	pacman -Sy --noconfirm --needed docker bind fuse-overlayfs
elif command -v apt-get >/dev/null 2>&1; then
	export DEBIAN_FRONTEND=noninteractive
	apt-get update
	apt-get install -y --no-install-recommends docker-ce containerd.io dnsutils fuse-overlayfs
elif command -v dnf >/dev/null 2>&1; then
	dnf -y install docker-ce containerd.io bind-utils fuse-overlayfs
elif command -v yum >/dev/null 2>&1; then
	yum -y install docker-ce containerd.io bind-utils fuse-overlayfs
else
	echo "no supported package manager for docker daemon install" >&2
	exit 1
fi
