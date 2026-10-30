#!/usr/bin/env bash
# Param: $1  pacman.conf to rewrite; a missing file means no pacman, nothing is layered; the publish hook goes to pacman.d/hooks/ beside it
# Param: $2  shared infinito cache root; pacman downloads into <root>/pacman/node-XXXXXX/ and publishes into <root>/pacman/
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

if grep -qE '^[[:space:]]*HookDir[[:space:]]*=' "${CONF}"; then
	echo "[pacman-cache] ${CONF} sets HookDir, so pacman would not read the publish hook in its default hook directory" >&2
	exit 1
fi

if [ -n "${HOST}" ] && [ ! -d "${HOST}" ]; then
	echo "[pacman-cache] host cache ${HOST} is not mounted" >&2
	exit 1
fi

OWN="${SHARED%/}/pacman"
mkdir -p "${OWN}"

STAGE="$(awk -v prefix="CacheDir = ${OWN}/node-" '
	index($0, prefix) == 1 { line = substr($0, 12); sub(/\/$/, "", line); print line; exit }
' "${CONF}")"
if [ -n "${STAGE}" ]; then
	mkdir -p "${STAGE}"
else
	STAGE="$(mktemp -d "${OWN}/node-XXXXXX")"
fi
chmod 0755 "${STAGE}"

layered="$(mktemp)"
trap 'rm -f "${layered}"' EXIT
awk -v host="${HOST%/}" -v stage="${STAGE}" -v own="${OWN}" '
	/^[[:space:]]*CacheDir[[:space:]]*=/ { next }
	{ print }
	$0 == "[options]" {
		if (host != "") print "CacheDir = " host "/"
		print "CacheDir = " stage "/"
		print "CacheDir = " own "/"
	}
' "${CONF}" >"${layered}"
cat "${layered}" >"${CONF}"

HOOKS="$(dirname "${CONF}")/pacman.d/hooks"
mkdir -p "${HOOKS}"
printf '%s\n' \
	'[Trigger]' \
	'Operation = Install' \
	'Operation = Upgrade' \
	'Type = Package' \
	'Target = *' \
	'' \
	'[Action]' \
	'Description = Publishing downloaded packages to the shared pacman cache...' \
	'When = PostTransaction' \
	"Exec = /usr/bin/find \"${STAGE}\" -maxdepth 1 -type f ! -name *.part -exec /usr/bin/mv -f -t \"${OWN}\" {} +" \
	>"${HOOKS}/infinito-shared-cache.hook"

echo "[pacman-cache] CacheDir: ${HOST:+${HOST%/}/ (read-only), }${STAGE}/ (downloads), ${OWN}/" >&2
