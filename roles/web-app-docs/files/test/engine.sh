#!/bin/sh
# shellcheck shell=sh
#
# A block that deploys the machine itself must NOT get this: sys-svc-container
# replaces the engine with docker-ce, and its docker.service restart fails
# when the running docker.socket belongs to the package being replaced.

set -e

install_engine() {
	if command -v dockerd >/dev/null 2>&1 && command -v docker >/dev/null 2>&1; then
		return 0
	fi

	if command -v apt-get >/dev/null 2>&1; then
		apt-get update
		DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends docker.io
		command -v docker >/dev/null 2>&1 ||
			DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends docker-cli
		rm -rf /var/lib/apt/lists/*
	elif command -v dnf >/dev/null 2>&1; then
		dnf install -y --allowerasing docker
		dnf clean all
	elif command -v pacman >/dev/null 2>&1; then
		pacman -Sy --noconfirm --needed docker
		rm -rf /var/cache/pacman/pkg/*
	else
		echo "no supported package manager to install a container engine with" >&2
		exit 1
	fi

	if ! command -v docker >/dev/null 2>&1; then
		echo "the container engine install left no docker client on PATH" >&2
		exit 1
	fi
}

install_engine
systemctl enable --now docker.service
