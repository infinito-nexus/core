#!/usr/bin/env bash
# shellcheck shell=bash
#
# Criterion K measurements for the Wazuh host agent, dev stack only; never deployed, never run in CI.
# Runs inside the dev container (make compose-exec) and prints one markdown result row per case.
#
# Usage: measure_k.sh <case>
#   normal          1,000 numbered events at about 50/s
#   burst-buffer    20,000 events as fast as one container prints, above the agent's EPS
#   burst-journald  80,000 events within 30 s, above journald's docker.service limit
#   outage-5        10 events/s while the manager is stopped for 5 minutes
#   outage-15       120 events/s while the manager is stopped for 15 minutes, which overflows the buffer
#   agent-restart   200 events while the agent is stopped
#   restart-frozen  10 events/s; the manager stops, the agent restarts while its collector is frozen, the manager returns
#   agent-down      the agent stopped past the health check's grace, then one health check run
#   journal-check   an app error and a daemon error, then one journal health check run
#
# Env (all required):
#   K_TAG            the opted-in journald tag the events use
#   K_IMAGE          image of the throwaway log containers
#   K_MANAGER        name of the Wazuh manager container
#   K_LOGS_VOLUME    Docker volume holding the manager's logs
#   K_MANAGER_CONF   the rendered manager ossec.conf on the host
#   K_AGENT_STATE    the agent's wazuh-agentd.state
#   K_HEALTH_UNIT    the agent health check's systemd service
#   K_JOURNAL_UNIT   the journal health check's systemd service
#   K_WATCH_TAG      journald tag of the collector freeze messages
#   K_SETTLE_S       seconds the archive count must stay unchanged before counting
#   K_MAX_WAIT_S     upper bound for that wait

set -euo pipefail

CASE="${1:?usage: measure_k.sh <case>}"
: "${K_TAG:?}" "${K_IMAGE:?}" "${K_MANAGER:?}" "${K_LOGS_VOLUME:?}" "${K_MANAGER_CONF:?}"
: "${K_AGENT_STATE:?}" "${K_HEALTH_UNIT:?}" "${K_JOURNAL_UNIT:?}" "${K_SETTLE_S:?}" "${K_MAX_WAIT_S:?}" "${K_WATCH_TAG:?}"

RUN="$(date -u +%Y%m%dT%H%M%S)-$$"
LABEL="infinito-wazuh-k=${RUN}"
MARK="K-${RUN}"
LOGS_DIR="$(docker volume inspect -f '{{.Mountpoint}}' "${K_LOGS_VOLUME}")"
ARCHIVES="${LOGS_DIR}/archives/archives.json"
ALERTS="${LOGS_DIR}/alerts/alerts.json"
START_EPOCH="$(date +%s)"

restore() {
	docker ps -aq --filter "label=${LABEL}" | xargs -r docker rm -f >/dev/null
	if [[ "$(docker inspect --type container -f '{{.State.Running}}' "${K_MANAGER}")" != "true" ]]; then
		docker start "${K_MANAGER}" >/dev/null
	fi
	if ! systemctl is-active --quiet wazuh-agent; then
		systemctl start wazuh-agent
	fi
}
trap restore EXIT

fail() {
	echo "FAIL: $*" >&2
	exit 1
}

state() {
	sed -n "s/^$1='\(.*\)'$/\1/p" "${K_AGENT_STATE}"
}

wait_connected() {
	local waited=0
	until [[ "$(state status)" == "connected" && "$(state msg_buffer)" == "0" ]]; do
		[[ "${waited}" -lt "${K_MAX_WAIT_S}" ]] || fail "agent not connected with an empty buffer after ${K_MAX_WAIT_S} s"
		sleep 5
		waited=$((waited + 5))
	done
}

precondition() {
	grep -q '<logall_json>yes</logall_json>' "${K_MANAGER_CONF}" || fail "the manager archive (logall_json) is off"
	[[ -f "${ARCHIVES}" ]] || fail "no archive at ${ARCHIVES}"
	[[ "$(docker inspect --type container -f '{{.State.Running}}' "${K_MANAGER}")" == "true" ]] || fail "${K_MANAGER} is not running"
	wait_connected
	ARCHIVES_OFFSET="$(stat -c %s "${ARCHIVES}")"
	ALERTS_OFFSET="$(stat -c %s "${ALERTS}")"
	ARCHIVES_INODE="$(stat -c %i "${ARCHIVES}")"
}

emit() {
	docker run --rm --label "${LABEL}" --log-driver journald --log-opt "tag=${K_TAG}" "${K_IMAGE}" \
		sh -c "i=1; while [ \$i -le $1 ]; do echo '${MARK} seq='\$i; i=\$((i + 1)); $2; done" >/dev/null
}

emit_rate() {
	docker run --rm --label "${LABEL}" --log-driver journald --log-opt "tag=${K_TAG}" "${K_IMAGE}" \
		sh -c "i=1; while [ \$i -le $1 ]; do e=\$((i + $2 - 1)); [ \$e -gt $1 ] && e=$1; seq \$i \$e | sed 's/^/${MARK} seq=/'; i=\$((e + 1)); sleep 1; done" >/dev/null
}

emit_fast() {
	docker run --rm --label "${LABEL}" --log-driver journald --log-opt "tag=${K_TAG}" "${K_IMAGE}" \
		sh -c "seq 1 $1 | sed 's/^/${MARK} seq=/'" >/dev/null
}

archived_seqs() {
	tail -c +"$((ARCHIVES_OFFSET + 1))" "${ARCHIVES}" | grep -aoE "${MARK} seq=[0-9]+" | sed 's/.*seq=//' || [[ $? -eq 1 ]]
}

wait_settled() {
	local last=-1 now stable=0 waited=0
	while [[ "${stable}" -lt "${K_SETTLE_S}" ]]; do
		[[ "${waited}" -lt "${K_MAX_WAIT_S}" ]] || break
		sleep 10
		waited=$((waited + 10))
		now="$(archived_seqs | wc -l)"
		if [[ "${now}" -eq "${last}" ]]; then stable=$((stable + 10)); else stable=0; fi
		last="${now}"
	done
	[[ "$(stat -c %i "${ARCHIVES}")" == "${ARCHIVES_INODE}" ]] || fail "the archive rotated during the run; repeat it"
}

alert_count() {
	tail -c +"$((ALERTS_OFFSET + 1))" "${ALERTS}" | grep -ac "\"id\":\"$1\"" || [[ $? -eq 1 ]]
}

result_row() {
	local name="$1" rate="$2" sent="$3" started="$4" journal archived missing summary duplicates suppressed
	journal="$(journalctl --since "@${START_EPOCH}" -o cat "SYSLOG_IDENTIFIER=${K_TAG}" | grep -ac "^${MARK} seq=" || [[ $? -eq 1 ]])"
	archived="$(archived_seqs | sort -un | wc -l)"
	duplicates="$(archived_seqs | sort -n | uniq -d | wc -l)"
	missing="$(archived_seqs | sort -un | awk -v n="${sent}" '
		{ seen[$1] = 1 }
		END {
			out = ""; start = 0
			for (i = 1; i <= n + 1; i++) {
				if (i <= n && !(i in seen)) { if (!start) start = i }
				else if (start) { out = out (out ? ", " : "") (start == i - 1 ? start : start "-" (i - 1)); start = 0 }
			}
			print (out ? out : "none")
		}')"
	summary="$(awk -F', ' '$0 == "none" { print "none"; next } { print NF " ranges, first " $1 ", last " $NF }' <<<"${missing}")"
	suppressed="$(journalctl --since "@${START_EPOCH}" -o cat SYSLOG_IDENTIFIER=systemd-journald |
		sed -n 's/^Suppressed \([0-9]*\) messages from docker\.service.*/\1/p' | awk '{ s += $1 } END { print s + 0 }')"
	printf '| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' \
		"${name}" "${rate}" "${sent}" "${journal}" "${archived}" "$((sent - journal))" "$((journal - archived))" \
		"${summary}" "${duplicates}" "${suppressed} ($(alert_count 100140))" \
		"$(alert_count 202)" "$(alert_count 203)" "$(alert_count 204)" "$(($(date +%s) - started))s"
	echo
	echo "Missing seq (${name}): ${missing}"
}

agent_memory() {
	local cgroup pid name
	cgroup="/sys/fs/cgroup$(systemctl show -p ControlGroup --value wazuh-agent)"
	while read -r pid; do
		name="$(cat "/proc/${pid}/comm")"
		case "${name}" in
		wazuh-agentd | wazuh-logcollec) echo "${name} $(awk -v key="$1:" '$1 == key { print $2 " kB" }' "/proc/${pid}/status")" ;;
		esac
	done <"${cgroup}/cgroup.procs"
}

header() {
	echo "| Case | Rate | Sent | In journald | In archive | Lost in journald | Lost in agent/transport | Missing seq | Duplicates | Suppressed (100140) | 202 | 203 | 204 | Duration |"
	echo "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
}

run_load() {
	local name="$1" count="$2" started emitted idle
	precondition
	idle="$(agent_memory VmRSS | paste -sd ',' -)"
	started="$(date +%s)"
	if [[ "$3" == "fast" ]]; then emit_fast "${count}"; else emit "${count}" "$3"; fi
	emitted="$(($(date +%s) - started))"
	wait_settled
	header
	result_row "${name}" "${count} in ${emitted}s" "${count}" "${started}"
	echo "Agent RSS before (${name}): ${idle}"
	echo "Agent RSS peak since process start (${name}): $(agent_memory VmHWM | paste -sd ',' -)"
}

buffer_alerts() {
	tail -c +"$((ALERTS_OFFSET + 1))" "${ALERTS}" |
		grep -aoE '"timestamp":"[^"]+".*"id":"20[234]"' |
		sed -E 's/^"timestamp":"([^"]+)".*"id":"(20[234])"$/\2 at \1/' || [[ $? -eq 1 ]]
}

run_outage() {
	local minutes="$1" rate="$2" count started stopped restarted
	count=$(((minutes * 60 + 120) * rate))
	precondition
	started="$(date +%s)"
	emit_rate "${count}" "${rate}" &
	sleep 30
	docker stop "${K_MANAGER}" >/dev/null
	stopped="$(date -u +%FT%T)"
	sleep $((minutes * 60))
	docker start "${K_MANAGER}" >/dev/null
	restarted="$(date -u +%FT%T)"
	wait
	wait_connected
	wait_settled
	header
	result_row "outage ${minutes} min" "${rate}/s" "${count}" "${started}"
	echo "Manager stopped ${stopped}Z, started ${restarted}Z"
	echo "Buffer alerts (id at alert timestamp):"
	buffer_alerts
	echo "Collector watch (${K_WATCH_TAG}):"
	journalctl --since "@${START_EPOCH}" -o short-iso "SYSLOG_IDENTIFIER=${K_WATCH_TAG}"
}

run_restart_frozen() {
	local rate=10 count=3000 started
	precondition
	started="$(date +%s)"
	emit_rate "${count}" "${rate}" &
	sleep 30
	docker stop "${K_MANAGER}" >/dev/null
	sleep 60
	systemctl restart wazuh-agent
	sleep 60
	docker start "${K_MANAGER}" >/dev/null
	wait
	wait_connected
	wait_settled
	header
	result_row "agent restart while frozen" "${rate}/s" "${count}" "${started}"
	echo "Collector watch (${K_WATCH_TAG}):"
	journalctl --since "@${START_EPOCH}" -o short-iso "SYSLOG_IDENTIFIER=${K_WATCH_TAG}"
}

run_agent_restart() {
	local started
	precondition
	started="$(date +%s)"
	systemctl stop wazuh-agent
	emit_fast 200
	systemctl start wazuh-agent
	wait_connected
	wait_settled
	header
	result_row "agent stopped, 200 written" "fast" 200 "${started}"
}

run_agent_down() {
	local rc=0 alarm
	precondition
	systemctl stop wazuh-agent
	sleep 200
	systemctl start "${K_HEALTH_UNIT}" || rc=$?
	sleep 10
	alarm="$(journalctl --since "@${START_EPOCH}" -o cat -u "alm-compose*@${K_HEALTH_UNIT}*" | wc -l)"
	echo "agent-down: ${K_HEALTH_UNIT} exit ${rc}, result $(systemctl show -p Result --value "${K_HEALTH_UNIT}"), alarm unit journal lines ${alarm}"
}

run_journal_check() {
	local output rc=0
	precondition
	docker run --rm --label "${LABEL}" --log-driver journald --log-opt "tag=${K_TAG}" "${K_IMAGE}" \
		echo "error ${MARK} app" >/dev/null
	logger -t dockerd "error ${MARK} daemon"
	systemctl start "${K_JOURNAL_UNIT}" || rc=$?
	echo "journal-check: ${K_JOURNAL_UNIT} exit ${rc}"
	journalctl --sync
	output="$(journalctl --since "@${START_EPOCH}" -o cat "_SYSTEMD_UNIT=${K_JOURNAL_UNIT}")"
	echo "journal-check: daemon error reported: $(grep -qF "error ${MARK} daemon" <<<"${output}" && echo yes || echo no), app error reported: $(grep -qF "error ${MARK} app" <<<"${output}" && echo yes || echo no)"
	echo "Reported marker lines (a copy is a line another journal check unit logged again):"
	grep -F "${MARK}" <<<"${output}" | awk '{ print (/^hlth-journalctl\.[^:]*\.service: / ? "[copy from stale unit] " : "[original] ") $0 }' ||
		[[ $? -eq 1 ]]
}

case "${CASE}" in
normal) run_load "normal" 1000 "sleep 0.02" ;;
burst-buffer) run_load "burst above the agent buffer" 20000 fast ;;
burst-journald) run_load "burst above journald" 80000 fast ;;
outage-5) run_outage 5 10 ;;
outage-15) run_outage 15 120 ;;
agent-restart) run_agent_restart ;;
restart-frozen) run_restart_frozen ;;
agent-down) run_agent_down ;;
journal-check) run_journal_check ;;
*) fail "unknown case ${CASE}" ;;
esac
