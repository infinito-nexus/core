#!/usr/bin/env bash
# Param: $1  pacman.conf to rewrite; a missing file means no pacman, nothing is layered
# Param: $2  shared infinito cache root; pacman writes below <root>/pacman/
# Param: $3  read-only host pacman cache, mounted at the same path; empty leaves that layer out
set -euo pipefail

CONF="${1:?usage: pacman.sh <pacman.conf> <shared-cache-root> <host-pacman-cache|''>}"
SHARED="${2:?usage: pacman.sh <pacman.conf> <shared-cache-root> <host-pacman-cache|''>}"
HOST="${3?usage: pacman.sh <pacman.conf> <shared-cache-root> <host-pacman-cache|''>}"

if [ ! -f "${CONF}" ]; then
	echo "[pacman-cache] ${CONF} absent; no pacman to layer" >&2
	exit 0
fi

grep -qx '\[options\]' "${CONF}" || {
	echo "[pacman-cache] ${CONF} has no [options] section to carry CacheDir" >&2
	exit 1
}

if [ -n "${HOST}" ] && [ ! -d "${HOST}" ]; then
	echo "[pacman-cache] host cache ${HOST} is not mounted" >&2
	exit 1
fi

OWN="${SHARED%/}/pacman"
mkdir -p "${OWN}"

layered="$(mktemp)"
trap 'rm -f "${layered}"' EXIT
awk -v host="${HOST%/}" -v own="${OWN}" '
	/^[[:space:]]*CacheDir[[:space:]]*=/ { next }
	{ print }
	$0 == "[options]" {
		if (host != "") print "CacheDir = " host "/"
		print "CacheDir = " own "/"
	}
' "${CONF}" >"${layered}"
cat "${layered}" >"${CONF}"

echo "[pacman-cache] CacheDir: ${HOST:+${HOST%/}/ (read-only), }${OWN}/" >&2
