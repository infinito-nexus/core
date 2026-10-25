#!/usr/bin/env bash
# shellcheck shell=bash
#
# Env (rendered into test.env from templates/test.env.j2):
#   AGENT_ORCHESTRATOR_CONTAINER           resolved orchestrator container (CLI_LOCAL_CID)
#   AGENT_ORCHESTRATOR_PORT                orchestrator port inside the container
#   AGENT_ORCHESTRATOR_KEY_B64             base64 management bearer key
#   AGENT_ORCHESTRATOR_WEBHOOK_SECRET_B64  base64 webhook secret
#   REQUEST_TIMEOUT                        seconds a probe waits

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR_KEY="$(printf '%s' "${AGENT_ORCHESTRATOR_KEY_B64}" | base64 -d)"
WEBHOOK_SECRET="$(printf '%s' "${AGENT_ORCHESTRATOR_WEBHOOK_SECRET_B64}" | base64 -d)"
BODY='{"action":"opened"}'
FAILED=0

fail() {
	echo "[FAIL] $*" >&2
	FAILED=1
}

probe() {
	# nocheck: container-exec-resolver  container resolved by the harness and passed in
	container exec -i \
		-e "PORT=${AGENT_ORCHESTRATOR_PORT}" \
		-e "METHOD=$1" \
		-e "REQ_PATH=$2" \
		-e "KEY=$3" \
		-e "SECRET=$4" \
		-e "SIG_OVERRIDE=$5" \
		-e "DELIVERY=$6" \
		-e "BODY=$7" \
		-e "TIMEOUT=${REQUEST_TIMEOUT}" \
		"${AGENT_ORCHESTRATOR_CONTAINER}" python3 - <"${here}/probe.py"
}

status_of() {
	printf '%s\n' "$1" | sed -n 's/^STATUS //p'
}

out="$(probe GET /health "" "" "" "" "")"
[ "$(status_of "${out}")" = "200" ] || fail "/health answered $(status_of "${out}"), not 200"

out="$(probe GET /status "" "" "" "" "")"
[ "$(status_of "${out}")" = "401" ] || fail "/status without the key answered $(status_of "${out}"), not 401"

out="$(probe GET /status "${ORCHESTRATOR_KEY}" "" "" "" "")"
[ "$(status_of "${out}")" = "200" ] || fail "/status with the key answered $(status_of "${out}"), not 200"

out="$(probe POST /webhooks/github "" "" "sha256=deadbeef" "d1" "${BODY}")"
[ "$(status_of "${out}")" = "401" ] || fail "a webhook with a bad signature answered $(status_of "${out}"), not 401"

out="$(probe POST /webhooks/github "" "${WEBHOOK_SECRET}" "" "d1" "${BODY}")"
[ "$(status_of "${out}")" = "202" ] || fail "a signed webhook answered $(status_of "${out}"), not 202"

out="$(probe POST /webhooks/github "" "${WEBHOOK_SECRET}" "" "d1" "${BODY}")"
[ "$(status_of "${out}")" = "200" ] || fail "a repeated delivery id answered $(status_of "${out}"), not 200 (dropped)"

[ "${FAILED}" -eq 0 ] && echo "[OK] orchestrator verified signature, dedup and management auth"
exit "${FAILED}"
