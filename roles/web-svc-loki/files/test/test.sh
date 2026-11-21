#!/usr/bin/env bash
set -euo pipefail

: "${LOKI_TEST_IS_STACK_HOST:?}"
: "${LOKI_TEST_NETWORK:?}"
: "${LOKI_TEST_SERVICE_URL:?}"
: "${LOKI_TEST_PUSH_URL:?}"
: "${LOKI_TEST_TENANT:?}"
: "${LOKI_TEST_PUSH_TOKEN_B64:?}"
: "${LOKI_TEST_LOG_LABEL:?}"
: "${LOKI_TEST_REPLACEMENT_B64:?}"
: "${LOKI_TEST_IMAGE:?}"
: "${LOKI_TEST_CA_FILE?}"
: "${LOKI_TEST_SELF_APPLICATION:?}"
: "${LOKI_TEST_ALERT_NAME:?}"
: "${LOKI_TEST_ALERTMANAGER_URL?}"
: "${LOKI_TEST_ALERTMANAGER_NETWORK?}"

if [ "${LOKI_TEST_IS_STACK_HOST}" != "true" ]; then
	echo "SKIP: not the stack host of the Loki store"
	exit 0
fi

probe="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/loki_probe.py"

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
payload() {
	printf '{"streams":[{"stream":{"application":"loki-canary","log_class":"application"},"values":[["%s","%s"]]}]}' "$(date +%s%N)" "$1"
}

contract_run() {
	local application="$1"
	shift
	container run --rm \
		--label "${LOKI_TEST_LOG_LABEL}=${application}" \
		--log-driver journald \
		--log-opt "tag=${application}" \
		--log-opt "labels=${LOKI_TEST_LOG_LABEL}" \
		"$@"
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
contract_run loki-canary "${LOKI_TEST_IMAGE}" \
	sh -c "echo 'INFINITO-SOURCE-CANARY ${run_id} password=${source_password} token=${source_token} Authorization: Bearer ${source_bearer}'"

network_get() {
	local network="$1"
	shift
	# nocheck: logging-driver  the probe's stdout is the Loki or Alertmanager answer this test parses, not an application log; in the journal its canary and alert texts would reach Loki again and match the critical pattern
	container run --rm --log-driver none --network "${network}" "${LOKI_TEST_IMAGE}" \
		wget -qO- -T 30 "$@"
}

loki_get() {
	local path="$1"
	shift
	local url
	url="$(python3 -I "${probe}" url "${LOKI_TEST_SERVICE_URL}${path}" "$@")"
	network_get "${LOKI_TEST_NETWORK}" --header "X-Scope-OrgID: ${LOKI_TEST_TENANT}" "${url}"
}

query_lines() {
	local marker="$1"
	local end start
	end="$(date +%s%N)"
	start="$((end - 3600000000000))"
	loki_get /loki/api/v1/query_range \
		"query={application=\"loki-canary\"} |= \"${marker}\"" \
		"start=${start}" \
		"end=${end}" \
		"limit=20" |
		python3 -I "${probe}" lines
}

count_lines() {
	local selector="$1"
	local marker="$2"
	loki_get /loki/api/v1/query \
		"query=sum(count_over_time(${selector} |= \"${marker}\" [1h]))" \
		"time=$(date +%s%N)" |
		python3 -I "${probe}" count
}

wait_for_line() {
	local marker="$1"
	local lines=""
	for _ in $(seq 1 60); do
		if ! lines="$(query_lines "${marker}")"; then
			lines=""
		fi
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

burst_lines=20000
burst_marker="INFINITO-BURST-CANARY ${run_id} "
contract_run loki-canary "${LOKI_TEST_IMAGE}" \
	sh -c "seq 1 ${burst_lines} | sed 's/^/${burst_marker}/'" >/dev/null
burst_stored=0
for _ in $(seq 1 90); do
	if ! burst_stored="$(count_lines '{application="loki-canary"}' "${burst_marker}")"; then
		burst_stored=0
	fi
	if [ "${burst_stored}" -ge "${burst_lines}" ]; then
		break
	fi
	sleep 2
done
if [ "${burst_stored}" -ne "${burst_lines}" ]; then
	echo "FAIL: burst: ${burst_stored} of the ${burst_lines} lines one container wrote are stored in Loki"
	exit 1
fi
echo "OK: burst: all ${burst_lines} lines one container wrote are stored in Loki"

excluded_marker="INFINITO-EXCLUSION-CANARY ${run_id}"
control_marker="INFINITO-EXCLUSION-CONTROL ${run_id}"
contract_run "${LOKI_TEST_SELF_APPLICATION}" "${LOKI_TEST_IMAGE}" sh -c "echo '${excluded_marker}'" >/dev/null
contract_run loki-canary "${LOKI_TEST_IMAGE}" sh -c "echo '${control_marker}'" >/dev/null
if ! wait_for_line "${control_marker}" >/dev/null; then
	echo "FAIL: self-exclusion: the control line written after the excluded one never reached Loki"
	exit 1
fi
if ! excluded_stored="$(count_lines '{source="journal"}' "${excluded_marker}")"; then
	echo "FAIL: self-exclusion: Loki did not answer the count of the excluded line"
	exit 1
fi
if [ "${excluded_stored}" -ne 0 ]; then
	echo "FAIL: self-exclusion: a line of ${LOKI_TEST_SELF_APPLICATION} reached Loki"
	exit 1
fi
echo "OK: self-exclusion: the collector drops the lines of ${LOKI_TEST_SELF_APPLICATION}"

alert_application="loki-alert-${run_id}"
alert_line="$(python3 -I "${probe}" alert-line "${run_id}")"
contract_run "${alert_application}" "${LOKI_TEST_IMAGE}" sh -c "echo '${alert_line}'" >/dev/null
fired=false
for _ in $(seq 1 60); do
	if loki_get /prometheus/api/v1/alerts | python3 -I "${probe}" firing "${LOKI_TEST_ALERT_NAME}" "${alert_application}"; then
		fired=true
		break
	fi
	sleep 5
done
if [ "${fired}" != "true" ]; then
	echo "FAIL: ruler: ${LOKI_TEST_ALERT_NAME} did not fire for the synthetic critical line of ${alert_application}"
	exit 1
fi
echo "OK: ruler: ${LOKI_TEST_ALERT_NAME} fires on a synthetic critical line"

if [ -z "${LOKI_TEST_ALERTMANAGER_URL}" ]; then
	echo "SKIP: ruler notification: no Alertmanager is deployed, so the ruler has no alert channel to notify"
	exit 0
fi
alertmanager_alerts() {
	network_get "${LOKI_TEST_ALERTMANAGER_NETWORK}" "${LOKI_TEST_ALERTMANAGER_URL}/api/v2/alerts"
}

delivered=false
for _ in $(seq 1 24); do
	if alertmanager_alerts | python3 -I "${probe}" delivered "${LOKI_TEST_ALERT_NAME}" "${alert_application}"; then
		delivered=true
		break
	fi
	sleep 5
done
if [ "${delivered}" != "true" ]; then
	echo "FAIL: ruler notification: the Alertmanager holds no active ${LOKI_TEST_ALERT_NAME} alert for ${alert_application}"
	exit 1
fi
echo "OK: ruler notification: the Alertmanager holds the ${LOKI_TEST_ALERT_NAME} alert, so its receivers notify"
