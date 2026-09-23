#!/usr/bin/env bash
# shellcheck shell=bash
#
# svc-ai-litellm routing test. Runs probe.py inside the gateway container, where
# the API answers on loopback and the backends resolve by container name, and
# asserts the published model list matches the backends this deployment enabled.
#
# Env (rendered into test.env from templates/test.env.j2):
#   LITELLM_CONTAINER          resolved gateway container (CLI_LOCAL_CID)
#   LITELLM_PORT               gateway http port inside the container
#   LITELLM_MASTER_KEY_B64     base64 master key (avoids shell-quoting issues)
#   LITELLM_CHAT_MODEL         the model every consumer asks for
#   LITELLM_CHAT_MODEL_SERVED  true|false
#   LITELLM_EXPECTED_MODELS    JSON list the config template published
#   LITELLM_LMSTUDIO_ALIASES   JSON list of aliases only LM Studio provides
#   LITELLM_REMOTE_ALIASES     JSON list of aliases a configured provider key adds
#   LITELLM_OLLAMA_ENABLED     true|false
#   LITELLM_LMSTUDIO_ENABLED   true|false
#   READY_RETRIES              gateway readiness attempts (default 30)
#   READY_SLEEP_SECONDS        wait between attempts (default 5)

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
READY_RETRIES="${READY_RETRIES:-30}"
READY_SLEEP_SECONDS="${READY_SLEEP_SECONDS:-5}"

MASTER_KEY="$(printf '%s' "${LITELLM_MASTER_KEY_B64}" | base64 -d 2>/dev/null)"
[ -n "${MASTER_KEY}" ] || {
	echo "[FATAL] LITELLM_MASTER_KEY_B64 missing or undecodable" >&2
	exit 2
}
[ -n "${LITELLM_CONTAINER}" ] || {
	echo "[FATAL] LITELLM_CONTAINER unset; the gateway container was not resolved" >&2
	exit 2
}

# The image ships the litellm app, so a python interpreter is present, but the
# upstream tag has changed which of the two names is on PATH.
interpreter() {
	# nocheck: container-exec-resolver  address resolved by the caller and passed in
	if container exec -i "${LITELLM_CONTAINER}" python3 -c '' 2>/dev/null; then
		echo python3
	else
		echo python
	fi
}

probe() {
	# nocheck: container-exec-resolver  address resolved by the caller and passed in
	container exec -i \
		-e "PORT=${LITELLM_PORT}" \
		-e "MASTER_KEY=${MASTER_KEY}" \
		-e "CHAT_MODEL=${LITELLM_CHAT_MODEL}" \
		-e "CHAT_MODEL_SERVED=${LITELLM_CHAT_MODEL_SERVED}" \
		-e "EXPECTED_MODELS=${LITELLM_EXPECTED_MODELS}" \
		-e "LMSTUDIO_ALIASES=${LITELLM_LMSTUDIO_ALIASES}" \
		-e "REMOTE_ALIASES=${LITELLM_REMOTE_ALIASES}" \
		-e "OLLAMA_ENABLED=${LITELLM_OLLAMA_ENABLED}" \
		-e "LMSTUDIO_ENABLED=${LITELLM_LMSTUDIO_ENABLED}" \
		-e "ROUTER_ALIAS=${LITELLM_ROUTER_ALIAS}" \
		-e "ROUTER_WINDOWS=${LITELLM_ROUTER_WINDOWS}" \
		"${LITELLM_CONTAINER}" "$(interpreter)" - <"${here}/probe.py"
}

attempt=1
while [ "${attempt}" -le "${READY_RETRIES}" ]; do
	output="$(probe 2>&1)"
	rc=$?
	case "${output}" in
	*"gateway answered /v1/models"*)
		echo "${output}"
		exit "${rc}"
		;;
	esac
	attempt=$((attempt + 1))
	[ "${attempt}" -le "${READY_RETRIES}" ] && sleep "${READY_SLEEP_SECONDS}"
done

echo "[FAIL] the gateway never answered /v1/models after ${READY_RETRIES} attempts" >&2
echo "${output}" >&2
exit 1
