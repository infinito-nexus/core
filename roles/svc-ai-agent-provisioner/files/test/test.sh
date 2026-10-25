#!/usr/bin/env bash
# shellcheck shell=bash
#
# Env (rendered into test.env from templates/test.env.j2):
#   AGENT_PROVISIONER_CONTAINER   resolved provisioner container (CLI_LOCAL_CID)
#   AGENT_PROVISIONER_PORT        provisioner port inside the container
#   AGENT_PROVISIONER_KEY_B64     base64 instance-API bearer key
#   REQUEST_TIMEOUT               seconds a probe waits

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVISIONER_KEY="$(printf '%s' "${AGENT_PROVISIONER_KEY_B64}" | base64 -d)"
KEY_A='{"name":"dev1","public_key":"keyA"}'
KEY_B='{"name":"dev1","public_key":"keyB"}'
FAILED=0

fail() {
	echo "[FAIL] $*" >&2
	FAILED=1
}

probe() {
	# nocheck: container-exec-resolver  container resolved by the harness and passed in
	container exec -i \
		-e "PORT=${AGENT_PROVISIONER_PORT}" \
		-e "METHOD=$1" \
		-e "REQ_PATH=$2" \
		-e "KEY=$3" \
		-e "BODY=$4" \
		-e "TIMEOUT=${REQUEST_TIMEOUT}" \
		"${AGENT_PROVISIONER_CONTAINER}" python3 - <"${here}/probe.py"
}

status_of() {
	printf '%s\n' "$1" | sed -n 's/^STATUS //p'
}

out="$(probe GET /health "" "")"
[ "$(status_of "${out}")" = "200" ] || fail "/health answered $(status_of "${out}"), not 200"

out="$(probe GET /status "" "")"
[ "$(status_of "${out}")" = "401" ] || fail "/status without the key answered $(status_of "${out}"), not 401"

out="$(probe GET /status "${PROVISIONER_KEY}" "")"
[ "$(status_of "${out}")" = "200" ] || fail "/status with the key answered $(status_of "${out}"), not 200"

out="$(probe POST /instances/register "${PROVISIONER_KEY}" "${KEY_A}")"
[ "$(status_of "${out}")" = "200" ] || fail "a first registration answered $(status_of "${out}"), not 200"

out="$(probe POST /instances/register "${PROVISIONER_KEY}" "${KEY_B}")"
[ "$(status_of "${out}")" = "409" ] || fail "a name claimed with a new key answered $(status_of "${out}"), not 409 (refused)"

out="$(probe POST /instances/register "${PROVISIONER_KEY}" "${KEY_A}")"
[ "$(status_of "${out}")" = "200" ] || fail "the same key re-registering answered $(status_of "${out}"), not 200 (renewed)"

[ "${FAILED}" -eq 0 ] && echo "[OK] provisioner verified management auth and the instance-registration takeover rule"
exit "${FAILED}"
