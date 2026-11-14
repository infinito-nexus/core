#!/usr/bin/env bash
# shellcheck shell=bash
# Env (rendered into test.env from templates/test.env.j2):
#   OPENPOST_CONTAINER   resolved OpenPost container (CLI_LOCAL_CID)
#   OPENPOST_RELAY_PORT  port the relay listens on inside the role network
#   every OPENPOST_* variable the openpost/ probe modules document

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ -n "${OPENPOST_CONTAINER}" ] || {
	echo "[FATAL] OPENPOST_CONTAINER unset; the OpenPost container was not resolved" >&2
	exit 2
}

python3 -E -s "${here}/probe.py"
rc=$?

# nocheck: container-exec-resolver, shell-download-retry  address resolved by the caller; a single attempt is the point of a refusal probe
unmapped="$(container exec "${OPENPOST_CONTAINER}" wget -S -T 10 -O /dev/null "https://relay:${OPENPOST_RELAY_PORT}/" 2>&1)"
case "${unmapped}" in
*"HTTP/"*)
	echo "[FAIL] the relay forwarded a TLS connection whose SNI is not in its map"
	echo "${unmapped}"
	rc=1
	;;
*)
	echo "[OK]   the relay refuses a TLS connection whose SNI is not in its map"
	;;
esac

exit "${rc}"
