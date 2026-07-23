#!/usr/bin/env bash
# Generic parallel-make wrapper. Takes one or more make targets as
# args, runs each as its own background `make` invocation (capped at
# INFINITO_WORKER_CPU concurrent workers), and at the end prints a
# per-target wall-clock breakdown plus the overall elapsed time.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

if [[ $# -eq 0 ]]; then
	echo "scripts/make/parallel.sh: at least one make target required" >&2 # nocheck: self-path-reference
	exit 2
fi

# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

: "${INFINITO_WORKER_CPU:?INFINITO_WORKER_CPU must be set (provided by default.env via the env loader)}"

n_targets=$#
if ((n_targets < INFINITO_WORKER_CPU)); then
	jobs="${n_targets}"
else
	jobs="${INFINITO_WORKER_CPU}"
fi

format_duration() {
	local seconds="$1"
	printf '%dm %02ds' "$((seconds / 60))" "$((seconds % 60))"
}

echo
echo "🚀  parallel make dispatch"
echo "    📋  targets:  $*"
echo "    ⚙️   jobs:     ${jobs}  (cpu cap: ${INFINITO_WORKER_CPU})"
echo

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

declare -A pid_to_target=()
declare -A target_start=()
declare -A target_dur=()
declare -A target_rc=()
declare -A target_log=()

start_ts="$(date +%s)"

# Concurrency throttle: launch up to ${jobs} children at a time. When
# the active count hits the cap, drain via wait -n before spawning more.
active=0
to_launch=("$@")
launch_idx=0

drain_one() {
	local pid=""
	local rc=0
	# `|| rc=$?` keeps set -e happy when a child exited non-zero.
	wait -n -p pid || rc=$?
	local tgt="${pid_to_target[${pid}]}"
	target_rc["${tgt}"]="${rc}"
	target_dur["${tgt}"]=$(($(date +%s) - target_start["${tgt}"]))
	if ((rc == 0)); then
		echo "✅  ${tgt}  ($(format_duration "${target_dur[${tgt}]}"))"
	else
		echo "❌  ${tgt}  ($(format_duration "${target_dur[${tgt}]}"))  exit=${rc}"
	fi
	cat "${target_log[${tgt}]}"
	active=$((active - 1))
}

for tgt in "${to_launch[@]}"; do
	while ((active >= jobs)); do
		drain_one
	done
	log="${tmpdir}/${launch_idx}.log"
	target_log["${tgt}"]="${log}"
	target_start["${tgt}"]="$(date +%s)"
	(make -- "${tgt}") >"${log}" 2>&1 &
	pid_to_target[$!]="${tgt}"
	active=$((active + 1))
	launch_idx=$((launch_idx + 1))
done

while ((active > 0)); do
	drain_one
done

total=$(($(date +%s) - start_ts))

echo
echo "📊  per-target wall-clock:"
overall_rc=0
for tgt in "$@"; do
	rc="${target_rc[${tgt}]}"
	if ((rc == 0)); then
		status="✅"
	else
		status="❌"
		overall_rc="${rc}"
	fi
	printf '    %s  %-30s %s\n' "${status}" "${tgt}" "$(format_duration "${target_dur[${tgt}]}")"
done

echo
if ((overall_rc == 0)); then
	echo "✨  total $(format_duration "${total}")  🎉"
else
	echo "💥  total $(format_duration "${total}")  (exit=${overall_rc})"
fi
echo

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
	{
		echo "## 🚀 Parallel make targets"
		echo
		echo "| Target | Status | Duration |"
		echo "|---|:---:|---:|"
		for tgt in "$@"; do
			if ((target_rc[${tgt}] == 0)); then
				status="✅"
			else
				status="❌ exit=${target_rc[${tgt}]}"
			fi
			# shellcheck disable=SC2016  # backticks are markdown, not expansion
			printf '| `%s` | %s | %s |\n' \
				"${tgt}" "${status}" "$(format_duration "${target_dur[${tgt}]}")"
		done
		if ((overall_rc == 0)); then
			printf '| **total** | ✨ | %s |\n' "$(format_duration "${total}")"
		else
			printf '| **total** | 💥 exit=%s | %s |\n' \
				"${overall_rc}" "$(format_duration "${total}")"
		fi
		echo
	} >>"${GITHUB_STEP_SUMMARY}"
fi

exit "${overall_rc}"
