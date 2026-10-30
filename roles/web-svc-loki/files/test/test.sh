#!/usr/bin/env bash
set -euo pipefail

: "${LOKI_TEST_IS_STACK_HOST:?}"
: "${LOKI_TEST_LOCAL_URL:?}"
: "${LOKI_TEST_PUSH_URL:?}"
: "${LOKI_TEST_TENANT:?}"
: "${LOKI_TEST_PUSH_TOKEN_B64:?}"
: "${LOKI_TEST_LOG_LABEL:?}"
: "${LOKI_TEST_REPLACEMENT_B64:?}"
: "${LOKI_TEST_IMAGE:?}"
: "${LOKI_TEST_CA_FILE?}"

if [ "${LOKI_TEST_IS_STACK_HOST}" != "true" ]; then
	echo "SKIP: not the stack host of the Loki store"
	exit 0
fi

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
chmod 0700 "${work}"

replacement="$(printf '%s' "${LOKI_TEST_REPLACEMENT_B64}" | base64 -d)"
auth_header="${work}/auth.header"
printf 'Authorization: Bearer %s\n' "$(printf '%s' "${LOKI_TEST_PUSH_TOKEN_B64}" | base64 -d)" >"${auth_header}"
chmod 0600 "${auth_header}"

tls_args=()
if [ -n "${LOKI_TEST_CA_FILE}" ]; then
	tls_args=(--cacert "${LOKI_TEST_CA_FILE}")
fi

run_id="$(date +%s%N)"
now_ns="$(date +%s%N)"
payload() {
	printf '{"streams":[{"stream":{"application":"loki-canary","log_class":"application"},"values":[["%s","%s"]]}]}' "${now_ns}" "$1"
}

push_status() {
	curl --max-time 30 -sS -o /dev/null -w '%{http_code}' "${tls_args[@]}" \
		-X POST -H 'Content-Type: application/json' "$@" \
		--data "$(payload "INFINITO-PUSH-PROBE ${run_id}")" "${LOKI_TEST_PUSH_URL}"
}

status="$(push_status -H "X-Scope-OrgID: ${LOKI_TEST_TENANT}")"
if [ "${status}" != "401" ]; then
	echo "FAIL: an unauthenticated push answered ${status}, expected 401"
	exit 1
fi
echo "OK: an unauthenticated push is refused"

status="$(push_status -H "@${auth_header}" -H "X-Scope-OrgID: ${LOKI_TEST_TENANT}-foreign")"
if [ "${status}" != "403" ]; then
	echo "FAIL: a push for a foreign tenant answered ${status}, expected 403"
	exit 1
fi
echo "OK: a push for a foreign tenant is refused"

gateway_secret="Canary-Gateway-Pass-${run_id}"
status="$(curl --max-time 30 -sS -o /dev/null -w '%{http_code}' "${tls_args[@]}" \
	-X POST -H 'Content-Type: application/json' -H "@${auth_header}" \
	-H "X-Scope-OrgID: ${LOKI_TEST_TENANT}" \
	--data "$(payload "INFINITO-GATEWAY-CANARY ${run_id} password=${gateway_secret}")" \
	"${LOKI_TEST_PUSH_URL}")"
if [ "${status}" != "204" ]; then
	echo "FAIL: an authenticated push answered ${status}, expected 204"
	exit 1
fi
echo "OK: an authenticated push is accepted"

source_password="Canary-Source-Pass-${run_id}"
source_token="Canary-Source-Token-${run_id}"
source_bearer="CanarySourceBearer${run_id}"
container run --rm \
	--label "${LOKI_TEST_LOG_LABEL}=loki-canary" \
	--log-driver journald \
	--log-opt "tag=loki-canary" \
	--log-opt "labels=${LOKI_TEST_LOG_LABEL}" \
	"${LOKI_TEST_IMAGE}" \
	sh -c "echo 'INFINITO-SOURCE-CANARY ${run_id} password=${source_password} token=${source_token} Authorization: Bearer ${source_bearer}'"

query_lines() {
	local marker="$1"
	local end start
	end="$(date +%s%N)"
	start="$((end - 3600000000000))"
	curl --max-time 30 -sS -G \
		-H "X-Scope-OrgID: ${LOKI_TEST_TENANT}" \
		--data-urlencode "query={application=\"loki-canary\"} |= \"${marker}\"" \
		--data-urlencode "start=${start}" \
		--data-urlencode "end=${end}" \
		--data-urlencode "limit=20" \
		"${LOKI_TEST_LOCAL_URL}/loki/api/v1/query_range" |
		python3 -I -c 'import json, sys; [print(v[1]) for s in json.load(sys.stdin)["data"]["result"] for v in s["values"]]'
}

wait_for_line() {
	local marker="$1"
	local lines=""
	for _ in $(seq 1 60); do
		lines="$(query_lines "${marker}")"
		if [ -n "${lines}" ]; then
			printf '%s\n' "${lines}"
			return 0
		fi
		sleep 2
	done
	return 1
}

assert_redacted() {
	local label="$1"
	local lines="$2"
	shift 2
	for secret in "$@"; do
		if printf '%s' "${lines}" | grep -qF -- "${secret}"; then
			echo "FAIL: ${label}: a canary secret reached Loki"
			exit 1
		fi
	done
	if ! printf '%s' "${lines}" | grep -qF -- "${replacement}"; then
		echo "FAIL: ${label}: the stored line carries no ${replacement} marker"
		exit 1
	fi
	echo "OK: ${label}: no canary secret is stored in Loki"
}

if ! gateway_lines="$(wait_for_line "INFINITO-GATEWAY-CANARY ${run_id}")"; then
	echo "FAIL: the gateway canary line never reached Loki"
	exit 1
fi
assert_redacted "central gateway stage" "${gateway_lines}" "${gateway_secret}"

if ! source_lines="$(wait_for_line "INFINITO-SOURCE-CANARY ${run_id}")"; then
	echo "FAIL: the application canary line never reached Loki within two minutes"
	exit 1
fi
assert_redacted "collector source stage" "${source_lines}" "${source_password}" "${source_token}" "${source_bearer}"
