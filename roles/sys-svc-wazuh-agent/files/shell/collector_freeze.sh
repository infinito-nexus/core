#!/usr/bin/env bash
# shellcheck shell=bash
#
# Freezes wazuh-logcollector while wazuh-agentd holds its offline lock. Wazuh 4.14.9's journald reader keeps
# reading while the agent is offline and drops every line its output queue cannot take, past its saved position;
# a frozen collector reads nothing and continues from its in-memory journal position when it is resumed.
#
# Usage: collector_freeze.sh <sync|release> <wait-file> <run-dir> <tag>
#   sync      SIGSTOP the collector while <wait-file> exists, SIGCONT it otherwise; repeats until the state holds
#   release   before the agent stops: a frozen collector gets SIGTERM, then SIGCONT, so it handles the pending
#             SIGTERM before it reads again and saves the position it was frozen at
#   wait-file wazuh-agentd's offline lock (queue/sockets/.wait)
#   run-dir   the agent's var/run directory with the daemons' PID files
#   tag       journald tag of the transition messages

set -euo pipefail

MODE="${1:?usage: collector_freeze.sh <sync|release> <wait-file> <run-dir> <tag>}"
WAIT_FILE="${2:?}"
RUN_DIR="${3:?}"
TAG="${4:?}"

collector_pid() {
	local pid_file pid
	for pid_file in "${RUN_DIR}"/wazuh-logcollector-*.pid; do
		[[ -e "${pid_file}" ]] || continue
		pid="${pid_file##*-}"
		pid="${pid%.pid}"
		if [[ -d "/proc/${pid}" ]]; then
			echo "${pid}"
			return 0
		fi
	done
	return 1
}

process_state() {
	sed -E 's/^.*\) ([A-Za-z]).*$/\1/' "/proc/$1/stat"
}

sync_once() {
	local pid
	pid="$(collector_pid)" || return 0
	if [[ -e "${WAIT_FILE}" ]]; then
		if [[ "$(process_state "${pid}")" != "T" ]]; then
			kill -STOP "${pid}"
			logger -t "${TAG}" "collector frozen pid=${pid}"
		fi
	elif [[ "$(process_state "${pid}")" == "T" ]]; then
		kill -CONT "${pid}"
		logger -t "${TAG}" "collector resumed pid=${pid}"
	fi
}

case "${MODE}" in
sync)
	for _ in 1 2 3 4 5 6 7 8 9 10; do
		before="$([[ -e "${WAIT_FILE}" ]] && echo locked || echo online)"
		sync_once
		after="$([[ -e "${WAIT_FILE}" ]] && echo locked || echo online)"
		[[ "${before}" == "${after}" ]] && exit 0
	done
	;;
release)
	pid="$(collector_pid)" || exit 0
	if [[ "$(process_state "${pid}")" == "T" ]]; then
		kill -TERM "${pid}"
		kill -CONT "${pid}"
		logger -t "${TAG}" "collector released for stop pid=${pid}"
	fi
	;;
*)
	echo "unknown mode ${MODE}" >&2
	exit 2
	;;
esac
