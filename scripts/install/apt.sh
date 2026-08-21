#!/usr/bin/env bash
set -euo pipefail

if (($# == 0)); then
	echo "Usage: $0 <package> [package ...]" >&2
	exit 1
fi

missing=()
for pkg in "$@"; do
	[[ "$(dpkg-query -W -f='${db:Status-Status}' "${pkg}" 2>/dev/null)" == installed ]] || missing+=("${pkg}")
done

if ((${#missing[@]} == 0)); then
	echo "[apt] already installed: $*"
	exit 0
fi

APT_TIMEOUT=10m
APT_OPTS=(-o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30)

sudo timeout -k 30 "${APT_TIMEOUT}" apt-get "${APT_OPTS[@]}" update
sudo timeout -k 30 "${APT_TIMEOUT}" apt-get "${APT_OPTS[@]}" install -y "${missing[@]}"
