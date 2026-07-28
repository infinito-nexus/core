#!/usr/bin/env bash
set -euo pipefail

# SPOT: run one command once per distro, in random order, under a shared time
# budget. A distro the budget drops is reported as skipped, not as a failure;
# only the per-distro command failing fails the run. Every outcome lands in a
# job-summary table in execution order.
#
# Param:
#   $@                                  command + args to run once per distro
#   INFINITO_DISTROS                    space-separated distro list
#   INFINITO_CI_DISTRO_BUDGET_SECONDS   wall-clock budget for the whole run
#   GITHUB_STEP_SUMMARY                 optional; the markdown table is appended there
#
# Exports per iteration:
#   INFINITO_DISTRO                     the distro under test

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/meta/env/load.sh
source "scripts/meta/env/load.sh"

: "${INFINITO_DISTROS:?INFINITO_DISTROS is required (e.g. 'arch debian ubuntu fedora centos')}"
: "${INFINITO_CI_DISTRO_BUDGET_SECONDS:?INFINITO_CI_DISTRO_BUDGET_SECONDS is required (declared in default.env)}"

if (($# == 0)); then
	echo "[ERROR] a per-distro command is required" >&2
	exit 2
fi

if ! [[ "${INFINITO_CI_DISTRO_BUDGET_SECONDS}" =~ ^[0-9]+$ ]]; then
	echo "[ERROR] INFINITO_CI_DISTRO_BUDGET_SECONDS must be an integer (seconds), got: '${INFINITO_CI_DISTRO_BUDGET_SECONDS}'" >&2
	exit 2
fi

read -r -a distro_arr <<<"${INFINITO_DISTROS}"
mapfile -t distro_arr < <(printf '%s\n' "${distro_arr[@]}" | shuf)
echo "=== Distro execution order: ${distro_arr[*]} ==="

global_start="$(date +%s)"
deadline="$((global_start + INFINITO_CI_DISTRO_BUDGET_SECONDS))"
echo "=== Global time budget: ${INFINITO_CI_DISTRO_BUDGET_SECONDS}s (deadline epoch=${deadline}) ==="

max_seen=0
skipped=0
ran=0
durations=()
statuses=()
seconds=()
notes=()

for _ in "${distro_arr[@]}"; do
	statuses+=("skipped")
	seconds+=("")
	notes+=("not reached within the budget")
done

# Renders the per-distro outcome to stdout and, when GITHUB_STEP_SUMMARY is set,
# appends the same run as a markdown table in execution order.
render_summary() {
	local i distro icon

	echo
	echo "=== Summary ==="
	echo "ran=${ran} skipped=${skipped}"
	echo "total_runtime=$(($(date +%s) - global_start))s max_seen_duration=${max_seen}s"
	echo "budget=${INFINITO_CI_DISTRO_BUDGET_SECONDS}s remaining=$((deadline - $(date +%s)))s"
	echo "per-distro:"
	for line in "${durations[@]}"; do
		echo "  - ${line}"
	done

	[[ -n "${GITHUB_STEP_SUMMARY:-}" ]] || return 0

	{
		echo "## 🐧 Distro coverage"
		echo
		echo "| # | Distro | Status | Duration | Note |"
		echo "|--:|---|:--:|--:|---|"
		for i in "${!distro_arr[@]}"; do
			distro="${distro_arr[$i]}"
			case "${statuses[$i]}" in
			passed) icon="✅ passed" ;;
			failed) icon="❌ failed" ;;
			*) icon="🟦 skipped" ;;
			esac
			# shellcheck disable=SC2016  # backticks are markdown, not expansion
			printf '| %s | `%s` | %s | %s | %s |\n' \
				"$((i + 1))" "${distro}" "${icon}" \
				"${seconds[$i]:+${seconds[$i]}s}" "${notes[$i]}"
		done
		echo
		echo "${ran}/${#distro_arr[@]} ran, ${skipped} skipped, budget ${INFINITO_CI_DISTRO_BUDGET_SECONDS}s, order randomised per run."
		echo
	} >>"${GITHUB_STEP_SUMMARY}"
}

for i in "${!distro_arr[@]}"; do
	distro="${distro_arr[$i]}"
	remaining="$((deadline - $(date +%s)))"

	if ((remaining <= 0)); then
		echo "[WARN] Global budget exhausted (remaining=${remaining}s). Stopping further distro runs."
		skipped=$((skipped + ${#distro_arr[@]} - i))
		notes[i]="budget exhausted"
		break
	fi

	if ((max_seen > 0 && remaining < max_seen)); then
		echo "[WARN] Skipping distro=${distro}: remaining=${remaining}s < max_seen=${max_seen}s (fast-fail heuristic)"
		skipped=$((skipped + 1))
		notes[i]="remaining ${remaining}s < slowest run ${max_seen}s"
		continue
	fi

	echo "=== Running distro=${distro}: ${1} ==="
	echo ">>> Time budget: remaining=${remaining}s max_seen=${max_seen}s"

	export INFINITO_DISTRO="${distro}"
	source "scripts/meta/env/load.sh"

	distro_start="$(date +%s)"

	set +e
	"$@"
	rc=$?
	set -e

	dur="$(($(date +%s) - distro_start))"
	durations+=("${distro}=${dur}s")
	ran=$((ran + 1))
	seconds[i]="${dur}"
	notes[i]=""

	if ((dur > max_seen)); then
		max_seen="$dur"
	fi

	echo ">>> Duration: distro=${distro} took ${dur}s (max_seen=${max_seen}s)"

	if [[ $rc -ne 0 ]]; then
		statuses[i]="failed"
		notes[i]="rc=${rc}"
		skipped=$((skipped + ${#distro_arr[@]} - i - 1))
		echo "[ERROR] Run failed for distro=${distro} (rc=${rc})" >&2
		render_summary
		exit "$rc"
	fi

	statuses[i]="passed"
done

render_summary
