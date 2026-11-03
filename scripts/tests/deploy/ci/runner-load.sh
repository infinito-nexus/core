#!/bin/sh
# Param: $1 start | loop | report
# Param: $2 sample file (default /tmp/runner-load.log)
# Param: RUNNER_LOAD_INTERVAL_S seconds between two samples (default 30)
set -eu

mode="${1:?mode required: start, loop or report}"
file="${2:-/tmp/runner-load.log}"
interval="${RUNNER_LOAD_INTERVAL_S:-30}"

sample() {
	read -r load1 _ </proc/loadavg
	read -r _ user nice system idle iowait irq softirq steal _ </proc/stat
	printf '%s %s %s %s %s %s %s\n' "$(date -u +%s)" "${load1}" \
		"$((user + nice))" "$((system + irq + softirq))" "${idle}" "${iowait}" "${steal}"
}

case "${mode}" in
start)
	: >"${file}"
	printf '%s|%s\n' "$(lscpu | sed -n 's/^Model name: *//p')" \
		"$(openssl speed -seconds 5 -bytes 16384 sha256 2>/dev/null | awk '/^sha256 /{print $NF}')" >"${file}.hw"
	nohup "$0" loop "${file}" >/dev/null 2>&1 &
	;;
loop)
	while :; do
		sample >>"${file}"
		sleep "${interval}"
	done
	;;
report)
	[ -s "${file}.hw" ] && awk -F'|' '{printf "runner cpu: %s, sha256 16k single core: %s\n", $1, $2}' "${file}.hw"
	[ -s "${file}" ] || {
		echo "no load samples in ${file}"
		exit 0
	}
	awk -v cores="$(nproc)" '
		NR == 1 { u0 = $3; s0 = $4; i0 = $5; w0 = $6; t0 = $7; first = $1 }
		{
			n++; sum += $2; if ($2 > max) max = $2; if ($2 > cores) over++
			u = $3; s = $4; i = $5; w = $6; t = $7; last = $1
		}
		END {
			total = (u - u0) + (s - s0) + (i - i0) + (w - w0) + (t - t0)
			if (total <= 0) total = 1
			printf "runner load over %d min on %d cores: load1 mean %.1f, max %.1f, above cores in %d%% of %d samples\n", \
				(last - first) / 60, cores, sum / n, max, 100 * over / n, n
			printf "cpu split: busy %.0f%% (user %.0f%%, system %.0f%%), iowait %.0f%%, idle %.0f%%, steal %.0f%%\n", \
				100 * ((u - u0) + (s - s0)) / total, 100 * (u - u0) / total, 100 * (s - s0) / total, \
				100 * (w - w0) / total, 100 * (i - i0) / total, 100 * (t - t0) / total
		}' "${file}"
	;;
*)
	echo "unknown mode: ${mode}" >&2
	exit 64
	;;
esac
