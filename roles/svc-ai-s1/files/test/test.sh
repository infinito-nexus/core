#!/usr/bin/env bash
# shellcheck shell=bash
#
# svc-ai-s1 System One test: runs probe.py inside the decider's container.
#
# Env (rendered into test.env from templates/test.env.j2):
#   S1_CONTAINER     resolved server container (CLI_LOCAL_CID)
#   S1_PORT          http port the server listens on inside the container
#   S1_MODEL_ALIAS   alias the API accepts in a request's model field
#   READY_RETRIES    readiness attempts (default 30)
#   READY_SLEEP_SECONDS wait between attempts (default 10)

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
READY_RETRIES="${READY_RETRIES:-30}"
READY_SLEEP_SECONDS="${READY_SLEEP_SECONDS:-10}"

[ -n "${S1_CONTAINER}" ] || {
	echo "[FATAL] S1_CONTAINER unset; the server container was not resolved" >&2
	exit 2
}

probe() {
	# nocheck: container-exec-resolver  address resolved by the caller and passed in
	container exec -i \
		-e "PORT=${S1_PORT}" \
		-e "MODEL=${S1_MODEL_ALIAS}" \
		"${S1_CONTAINER}" python3 - <"${here}/probe.py"
}

attempt=1
while [ "${attempt}" -le "${READY_RETRIES}" ]; do
	output="$(probe 2>&1)"
	rc=$?
	case "${output}" in
	*"[OK]"* | *"[FAIL]"*)
		echo "${output}"
		exit "${rc}"
		;;
	esac
	attempt=$((attempt + 1))
	[ "${attempt}" -le "${READY_RETRIES}" ] && sleep "${READY_SLEEP_SECONDS}"
done

echo "[FAIL] the System One server never answered after ${READY_RETRIES} attempts" >&2
echo "${output}" >&2
exit 1
