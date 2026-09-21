#!/usr/bin/env bash
# shellcheck shell=bash
#
# Env (rendered into test.env from templates/test.env.j2):
#   LMSTUDIO_CONTAINER        resolved container id on this node
#   LMSTUDIO_PORT             the daemon's HTTP port
#   LMSTUDIO_EXPECTED_MODELS  JSON array of model names the daemon must serve
#   LMSTUDIO_EXPECTED_BLOBS   JSON array of <repo>/<file> paths under models/
#   LMSTUDIO_EXPECTED_DIGESTS JSON array of sha256, aligned with the blobs
#   LMSTUDIO_MODELS_DIR       the models mount inside the container
#   RETRIES                   attempts       (default 30)
#   SLEEP_SECONDS             wait between   (default 10)

set -uo pipefail

RETRIES="${RETRIES:-30}"
SLEEP_SECONDS="${SLEEP_SECONDS:-10}"
MODELS_DIR="${LMSTUDIO_MODELS_DIR}"

[ -n "${LMSTUDIO_CONTAINER}" ] || {
	echo "[FATAL] LMSTUDIO_CONTAINER unset; the harness did not resolve a container" >&2
	exit 2
}

in_container() {
	container exec "${LMSTUDIO_CONTAINER}" "$@"
}

json_items() {
	python3 -c 'import json,sys; [print(x) for x in json.loads(sys.argv[1])]' "$1"
}

server_url=""

serves_model() {
	in_container curl -fsS --connect-timeout 5 --max-time 30 "${server_url}/v1/models" 2>/dev/null |
		python3 -c 'import json,sys; d=json.load(sys.stdin); print("\n".join(m.get("id","") for m in d.get("data",[])))' 2>/dev/null |
		grep -qxF "$1"
}

failed=0

echo "=== 1. the CLI authenticates against its own daemon ==="
attempt=1
auth_out=""
while [ "${attempt}" -le "${RETRIES}" ]; do
	if auth_out="$(in_container /app/.bundle/lms ls 2>&1)"; then
		echo "[OK]   lms ls authenticated"
		break
	fi
	if printf '%s' "${auth_out}" | grep -q 'authPacket'; then
		echo "[FAIL] the daemon rejected its own CLI: $(printf '%s' "${auth_out}" | grep -m1 authPacket)" >&2
		echo "       a second daemon shares /root/.lmstudio and rewrote .internal/lms-key-2" >&2
		exit 1
	fi
	attempt=$((attempt + 1))
	[ "${attempt}" -le "${RETRIES}" ] && sleep "${SLEEP_SECONDS}"
done
if [ "${attempt}" -gt "${RETRIES}" ]; then
	echo "[FAIL] lms ls never succeeded after ${RETRIES} attempts: ${auth_out}" >&2
	exit 1
fi

echo "=== 2. every declared blob is in place with its declared digest ==="
mapfile -t blobs < <(json_items "${LMSTUDIO_EXPECTED_BLOBS}")
mapfile -t digests < <(json_items "${LMSTUDIO_EXPECTED_DIGESTS}")
for i in "${!blobs[@]}"; do
	path="${MODELS_DIR}/${blobs[$i]}"
	if ! in_container test -f "${path}"; then
		echo "[FAIL] ${blobs[$i]} is not in the model store" >&2
		failed=1
		continue
	fi
	actual="$(in_container sha256sum "${path}" 2>/dev/null | awk '{print $1}')"
	if [ "${actual}" != "${digests[$i]}" ]; then
		echo "[FAIL] ${blobs[$i]} hashes to ${actual}, declared ${digests[$i]}" >&2
		failed=1
		continue
	fi
	echo "[OK]   ${blobs[$i]} present and matching"
done

echo "=== 3. the daemon serves every declared model on its network address ==="
address="$(in_container hostname -I | tr ' ' '\n' | grep -m1 -E '^[0-9]+(\.[0-9]+){3}$')"
if [ -z "${address}" ]; then
	echo "[FAIL] hostname -I reported no IPv4 address inside the container" >&2
	exit 1
fi
server_url="http://${address}:${LMSTUDIO_PORT}"
mapfile -t models < <(json_items "${LMSTUDIO_EXPECTED_MODELS}")
for model in "${models[@]}"; do
	attempt=1
	while [ "${attempt}" -le "${RETRIES}" ]; do
		if serves_model "${model}"; then
			echo "[OK]   ${model} is served"
			break
		fi
		attempt=$((attempt + 1))
		[ "${attempt}" -le "${RETRIES}" ] && sleep "${SLEEP_SECONDS}"
	done
	if [ "${attempt}" -gt "${RETRIES}" ]; then
		if ! in_container curl -fsS --connect-timeout 5 --max-time 30 -o /dev/null "${server_url}/v1/models"; then
			echo "[FAIL] ${server_url} does not answer" >&2
			echo "       other containers cannot reach the server; check that LMS_SERVER_HOST binds it beyond loopback" >&2
		else
			echo "[FAIL] ${model} is on disk but /v1/models never listed it" >&2
			echo "       the daemon did not index the store it was given at startup" >&2
		fi
		failed=1
	fi
done

[ "${failed}" -eq 0 ] || exit 1
echo "[OK]   svc-ai-lmstudio serves every declared model from the seeded store"
