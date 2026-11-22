#!/bin/sh
# Param: $1  log file the blocks are appended to
set -u

INTERVAL_SECONDS=60
TOP_PROCESSES=10

memory_fields() {
	awk '$1 ~ /^(MemTotal|MemAvailable|SwapTotal|SwapFree):$/ {sub(/:$/, "", $1); printf " %s_kB=%s", $1, $2}' "${1}"
}

load_fields() {
	read -r one five fifteen tasks _ <"${1}"
	printf ' %s %s %s %s' "${one}" "${five}" "${fifteen}" "${tasks}"
}

pressure_fields() {
	if [ -r "${1}" ]; then
		awk '{printf " %s %s %s", $1, $2, $3}' "${1}"
	else
		printf ' unavailable'
	fi
}

top_rows() {
	awk -v stamp="${1}" -v limit="${TOP_PROCESSES}" \
		'NR <= limit {exe = $3; sub(/:.*/, "", exe); printf "%s top pid=%s rss_kB=%s exe=%s\n", stamp, $1, $2, exe}'
}

sample_once() {
	stamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
	printf '%s mem%s\n' "${stamp}" "$(memory_fields "${1}/meminfo")"
	printf '%s load%s\n' "${stamp}" "$(load_fields "${1}/loadavg")"
	for resource in cpu memory io; do
		printf '%s psi %s%s\n' "${stamp}" "${resource}" "$(pressure_fields "${1}/pressure/${resource}")"
	done
	ps -eo pid=,rss=,comm= --sort=-rss | top_rows "${stamp}"
}

[ "${HOST_METRICS_SAMPLER_LIB:-}" = "1" ] && return 0

: "${1:?usage: host-metrics-sampler.sh <log file>}"
mkdir -p "$(dirname "${1}")"
while :; do
	sample_once /proc >>"${1}"
	sleep "${INTERVAL_SECONDS}"
done
