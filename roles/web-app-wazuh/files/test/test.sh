#!/usr/bin/env bash
# shellcheck shell=bash
#
# web-app-wazuh role test, dev and CI only (criteria B, I, J):
#   B  the same message text from the self-test tag and an app tag stays two alerts, one per tag
#   J  only an opted-in tag is forwarded, also after its container is recreated; the
#      Wazuh containers' own logs never are
#   I  synthetic credentials sent through the app's request paths appear nowhere in Wazuh
#
# Env (all required; the role's test.env carries them):
#   APP_ENTITY, APP_DECODER   an opted-in app's journald tag and parent decoder
#   APP_URL, APP_HOST         that app's local HTTP port and its Host header
#   CANARY_MARKER, CANARY_RULE  the canary text and the self-test canary rule
#   FOREIGN_ENTITY            a role's entity that is not opted in
#   OPTED_ENTITIES            every opted-in entity, space separated; empty skips the test
#   INDEXER_URL, INDEXER_USER, INDEXER_PASSWORD  the indexer API
#   MANAGER_LOGS_VOLUME       the Docker volume holding the manager's logs
#   SELFTEST_TAG, SELFTEST_DECODER  the reserved self-test tag and its decoder
#   RETRIES, SLEEP_SECONDS    polling for an alert
#   TEST_IMAGE                image of the throwaway log containers
#   WAZUH_CONTAINERS          the Wazuh containers' names, space separated

set -euo pipefail

: "${OPTED_ENTITIES?}"
if [[ -z "${OPTED_ENTITIES}" ]]; then
	echo "SKIP: no opted-in app"
	exit 0
fi

: "${APP_ENTITY:?}" "${APP_DECODER:?}" "${APP_URL:?}" "${APP_HOST:?}"
: "${CANARY_MARKER:?}" "${CANARY_RULE:?}" "${FOREIGN_ENTITY:?}" "${OPTED_ENTITIES:?}"
: "${INDEXER_URL:?}" "${INDEXER_USER:?}" "${INDEXER_PASSWORD:?}" "${MANAGER_LOGS_VOLUME:?}"
: "${SELFTEST_TAG:?}" "${SELFTEST_DECODER:?}" "${RETRIES:?}" "${SLEEP_SECONDS:?}"
: "${TEST_IMAGE:?}" "${WAZUH_CONTAINERS:?}"

RUN="$(date -u +%Y%m%dT%H%M%S)-$$"
LABEL="infinito-wazuh-test=${RUN}"
LOGS_DIR="$(container volume inspect -f '{{.Mountpoint}}' "${MANAGER_LOGS_VOLUME}")"
ARCHIVES="${LOGS_DIR}/archives/archives.json"
ALERTS="${LOGS_DIR}/alerts/alerts.json"

cleanup() {
	container ps -aq --filter "label=${LABEL}" | xargs -r container rm -f >/dev/null
}
trap cleanup EXIT

fail() {
	echo "FAIL: $*" >&2
	exit 1
}

pass() {
	echo "PASS: $*"
}

emit() {
	container run --rm --name="wazuh-test-$2-${RUN}" --label="${LABEL}" \
		--log-driver=journald --log-opt="tag=$1" "${TEST_IMAGE}" echo "$3" >/dev/null
}

count_lines() {
	awk -v a="$2" -v b="$3" 'index($0, a) && index($0, b) { n++ } END { print n + 0 }' "$1"
}

indexer_count() {
	curl -sk --connect-timeout 10 --max-time 30 -u "${INDEXER_USER}:${INDEXER_PASSWORD}" -H 'Content-Type: application/json' \
		"${INDEXER_URL}/$1/_count" -d "$2" |
		python3 -c 'import json, sys; print(json.load(sys.stdin)["count"])'
}

alert_query() {
	python3 -c 'import json, sys; print(json.dumps({"query": {"bool": {"filter": [
		{"term": {"decoder.name": sys.argv[1]}},
		{"match_phrase": {"full_log": sys.argv[2]}}]}}}))' "$1" "$2"
}

wait_alert() {
	local query attempt
	query="$(alert_query "$1" "$2")"
	for ((attempt = 0; attempt < RETRIES; attempt++)); do
		if [[ "$(indexer_count 'wazuh-alerts-*' "${query}")" -gt 0 ]]; then
			return 0
		fi
		sleep "${SLEEP_SECONDS}"
	done
	fail "no alert with decoder $1 and text '$2' after $((RETRIES * SLEEP_SECONDS)) s"
}

barrier() {
	local text="${CANARY_MARKER} barrier-$1-${RUN}"
	emit "${SELFTEST_TAG}" "barrier-$1" "${text}"
	wait_alert "${SELFTEST_DECODER}" "${text}"
}

check_identical_text() {
	local text="${CANARY_MARKER} B-${RUN}" query
	emit "${SELFTEST_TAG}" b-selftest "${text}"
	emit "${APP_ENTITY}" b-app "${text}"
	wait_alert "${SELFTEST_DECODER}" "${text}"
	wait_alert "${APP_DECODER}" "${text}"
	query="$(python3 -c 'import json, sys; print(json.dumps({"query": {"bool": {"filter": [
		{"term": {"rule.id": sys.argv[1]}}, {"match_phrase": {"full_log": sys.argv[2]}}]}}}))' \
		"${CANARY_RULE}" "${text}")"
	[[ "$(indexer_count 'wazuh-alerts-*' "${query}")" -eq 2 ]] ||
		fail "B: expected exactly two canary alerts for '${text}'"
	pass "B: identical text from ${SELFTEST_TAG} and ${APP_ENTITY} stays two alerts with their own decoders"
}

check_per_app_switch() {
	local text="J-${RUN}" id name journal
	[[ " ${OPTED_ENTITIES} " != *" ${FOREIGN_ENTITY} "* ]] ||
		fail "J: ${FOREIGN_ENTITY} is opted in, so it cannot stand for an excluded app"
	[[ " ${OPTED_ENTITIES} " == *" ${APP_ENTITY} "* ]] || fail "J: ${APP_ENTITY} is not opted in"
	emit "${APP_ENTITY}" j-app "${text} first"
	emit "${FOREIGN_ENTITY}" j-foreign "${text} first"
	emit "${APP_ENTITY}" j-app "${text} recreated"
	emit "${FOREIGN_ENTITY}" j-foreign "${text} recreated"
	journal="$(journalctl --since -10min -o cat "SYSLOG_IDENTIFIER=${FOREIGN_ENTITY}" | grep -cF "${text}")" ||
		fail "J: the excluded tag ${FOREIGN_ENTITY} wrote nothing to journald"
	[[ "${journal}" -eq 2 ]] || fail "J: expected two journald lines from ${FOREIGN_ENTITY}, found ${journal}"
	barrier j
	[[ "$(count_lines "${ARCHIVES}" "${text}" "\"program_name\":\"${APP_ENTITY}\"")" -eq 2 ]] ||
		fail "J: the opted-in tag ${APP_ENTITY} did not arrive twice"
	[[ "$(count_lines "${ARCHIVES}" "${text}" "\"program_name\":\"${FOREIGN_ENTITY}\"")" -eq 0 ]] ||
		fail "J: the excluded tag ${FOREIGN_ENTITY} was forwarded"
	for name in ${WAZUH_CONTAINERS}; do
		id="$(container inspect --type container -f '{{.Id}}' "${name}" | cut -c1-12)"
		[[ "$(count_lines "${ARCHIVES}" "\"program_name\":\"${id}\"" '"location":"journald"')" -eq 0 ]] ||
			fail "J: the logs of ${name} were forwarded"
	done
	pass "J: only ${APP_ENTITY} is forwarded, also after recreation; ${FOREIGN_ENTITY} and the Wazuh containers are not"
}

check_secrets() {
	local password="SYNTHPW-${RUN}" bearer="SYNTHBEARER-${RUN}" key="SYNTHKEY-${RUN}"
	local reset="SYNTHRESET-${RUN}" confirm="SYNTHCONFIRM-${RUN}" referer="SYNTHREF-${RUN}"
	local secret where barrier_text="${CANARY_MARKER} i-barrier-${RUN}"
	local -a request=(curl -s --connect-timeout 10 --max-time 30 -o /dev/null -H "Host: ${APP_HOST}")
	"${request[@]}" -d "email=synthetic@example.invalid" -d "password=${password}" "${APP_URL}/login"
	"${request[@]}" -H "Authorization: Bearer ${bearer}" "${APP_URL}/api/v1/accounts/verify_credentials"
	"${request[@]}" "${APP_URL}/api/v1/timelines/home?access_token=${key}"
	"${request[@]}" "${APP_URL}/password/reset/${reset}"
	"${request[@]}" "${APP_URL}/i/confirm-email/${confirm}/${confirm}"
	"${request[@]}" -e "${APP_URL}/password/reset/${referer}" "${APP_URL}/"
	"${request[@]}" "${APP_URL}/${CANARY_MARKER}%20i-barrier-${RUN}"
	wait_alert "${APP_DECODER}" "${barrier_text}"
	for secret in "${password}" "${bearer}" "${key}" "${reset}" "${confirm}" "${referer}"; do
		for where in "${ARCHIVES}" "${ALERTS}"; do
			[[ "$(count_lines "${where}" "${secret}" "${secret}")" -eq 0 ]] ||
				fail "I: ${secret%%-*} found in ${where}"
		done
		[[ "$(indexer_count 'wazuh-*' "$(python3 -c 'import json, sys; print(json.dumps(
			{"query": {"query_string": {"query": "\"" + sys.argv[1] + "\""}}}))' "${secret}")")" -eq 0 ]] ||
			fail "I: ${secret%%-*} found in the indexer"
	done
	pass "I: no synthetic credential reached the archives, the alerts or the indexer"
}

check_identical_text
check_per_app_switch
check_secrets
