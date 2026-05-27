#!/usr/bin/env bash
# shellcheck shell=bash
# Auto-format all source files using available tools.
# Missing tools are reported and skipped rather than aborting the run.
#
# Per-tool workers run concurrently by default. Set INFINITO_WORKER_ENABLED=0
# (also accepts `false`/`no`/`off`) to fall back to sequential execution.
# Tools that touch the same files are kept on the same worker (the
# shfmt+shellcheck pair both writes to scripts/*.sh, so they share a
# worker) regardless of the parallelism setting.

set -euo pipefail

# Default lives in default.env (SPOT); load.sh exports it.
PARALLEL="${INFINITO_WORKER_ENABLED}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

# Per-worker status files live in a fresh dir under TMPDIR. We do NOT
# trap-delete on EXIT — that would race the background workers if the
# parent shell is interrupted mid-run (the trap fires, the dir
# disappears, an in-flight worker then tries to write its status file
# and crashes with "No such file or directory"). Cleanup happens
# explicitly after `wait` returns, see end of script.
status_dir="$(mktemp -d)"

write_status() {
	# $1 = tool name, $2 = OK|SKIP
	printf '%s %s\n' "$2" "$1" >"${status_dir}/$1"
}

# ── individual workers ───────────────────────────────────────────────────────

run_ruff() {
	if ! command -v ruff &>/dev/null; then
		write_status ruff SKIP
		return 0
	fi
	local rc=0
	ruff format . || rc=$?
	[[ $rc -eq 0 ]] && { ruff check . --fix || rc=$?; }
	if [[ $rc -eq 0 ]]; then
		write_status ruff OK
	else
		write_status ruff FAIL
	fi
}

run_claude() {
	if ! command -v python3 &>/dev/null; then
		write_status claude SKIP
		return 0
	fi
	if bash "${SCRIPT_DIR}/claude.sh"; then
		write_status claude OK
	else
		write_status claude FAIL
	fi
}

# shfmt + shellcheck both write to scripts/*.sh and therefore share a
# worker. They run sequentially within this function so their edits do
# not race.
run_shell_pair() {
	if ! command -v shfmt &>/dev/null; then
		write_status shfmt SKIP
	elif shfmt -w scripts; then
		write_status shfmt OK
	else
		write_status shfmt FAIL
	fi

	if command -v shellcheck &>/dev/null; then
		mapfile -t shellcheck_files < <(find . -type f -name '*.sh' 2>/dev/null | sort)
		if [[ "${#shellcheck_files[@]}" -gt 0 ]]; then
			local diff_file rc=0
			diff_file="$(mktemp)"
			set +e
			shellcheck -f diff -x "${shellcheck_files[@]}" >"${diff_file}" 2>/dev/null
			set -e
			if [[ -s "${diff_file}" ]]; then
				printf 'Applying ShellCheck autofixes.\n'
				git apply --whitespace=nowarn "${diff_file}" || rc=$?
			fi
			rm -f "${diff_file}"
			if [[ $rc -eq 0 ]]; then
				write_status shellcheck OK
			else
				write_status shellcheck FAIL
			fi
		else
			write_status shellcheck OK
		fi
	else
		write_status shellcheck SKIP
	fi
}

run_markdownlint() {
	if ! command -v markdownlint-cli2 &>/dev/null; then
		write_status markdownlint-cli2 SKIP
		return 0
	fi
	local rc=0
	markdownlint-cli2 --fix >/dev/null 2>&1 || rc=$?
	# rc=1 means "violations remain after fix" — that's expected when the
	# fixer can't auto-resolve everything; treat as OK. Only crashes
	# (rc>=2) count as FAIL.
	if [[ $rc -le 1 ]]; then
		write_status markdownlint-cli2 OK
	else
		write_status markdownlint-cli2 FAIL
	fi
}

run_ansible_lint() {
	if ! command -v ansible-lint &>/dev/null; then
		write_status ansible-lint SKIP
		return 0
	fi
	local rc=0
	ansible-lint --fix >/dev/null 2>&1 || rc=$?
	# ansible-lint exits 2 for violations, 0 for clean; both are normal
	# autoformat outcomes. Higher codes (3+) signal infrastructure errors.
	if [[ $rc -le 2 ]]; then
		write_status ansible-lint OK
	else
		write_status ansible-lint FAIL
	fi
}

run_mbake() {
	if ! command -v mbake &>/dev/null; then
		write_status mbake SKIP
		return 0
	fi
	local rc=0
	mbake format Makefile >/dev/null 2>&1 || rc=$?
	[[ $rc -eq 0 ]] && { mbake format Makefile >/dev/null 2>&1 || rc=$?; }
	if [[ $rc -eq 0 ]]; then
		write_status mbake OK
	else
		write_status mbake FAIL
	fi
}

run_eslint() {
	if [[ ! -d "node_modules/eslint" ]]; then
		write_status eslint SKIP
		return 0
	fi
	local rc=0
	# rc=1 means "violations remain after fix" — expected when the
	# fixer can't auto-resolve everything; treat as OK. Only crashes
	# (rc>=2) count as FAIL.
	npx --no-install eslint --fix 'roles/**/files/**/*.js' >/dev/null 2>&1 || rc=$?
	if [[ $rc -le 1 ]]; then
		write_status eslint OK
	else
		write_status eslint FAIL
	fi
}

# ── dispatch ─────────────────────────────────────────────────────────────────

is_truthy() {
	case "${1:-}" in
	1 | true | TRUE | True | yes | YES | Yes | on | ON | On) return 0 ;;
	*) return 1 ;;
	esac
}

workers=(run_ruff run_claude run_shell_pair run_markdownlint run_ansible_lint run_mbake run_eslint)

if is_truthy "${PARALLEL}"; then
	for w in "${workers[@]}"; do "${w}" & done
	# `|| true` so `set -e` does not abort the parent if any worker
	# exited non-zero — write_status has still run, and we want to reach
	# the summary block.
	wait || true
else
	for w in "${workers[@]}"; do "${w}" || true; done
fi

# ── summary ──────────────────────────────────────────────────────────────────

ran=()
failed=()
skipped=()
for f in "${status_dir}"/*; do
	[[ -f "${f}" ]] || continue
	line="$(<"${f}")"
	case "${line}" in
	OK\ *) ran+=("${line#OK }") ;;
	FAIL\ *) failed+=("${line#FAIL }") ;;
	SKIP\ *) skipped+=("${line#SKIP }") ;;
	esac
done

if [[ "${#ran[@]}" -gt 0 ]]; then
	printf 'autoformat: ran %s\n' "$(
		IFS=', '
		echo "${ran[*]}"
	)"
fi
if [[ "${#skipped[@]}" -gt 0 ]]; then
	printf 'autoformat: skipped (not installed) %s\n' "$(
		IFS=', '
		echo "${skipped[*]}"
	)"
fi
if [[ "${#failed[@]}" -gt 0 ]]; then
	printf 'autoformat: FAILED %s\n' "$(
		IFS=', '
		echo "${failed[*]}"
	)" >&2
fi

# Explicit cleanup after the summary. Reaches here only on a clean run;
# an interrupted run leaks the status_dir under TMPDIR (small, transient,
# auto-purged by the OS).
rm -rf "${status_dir}"

# Strict failure: any worker that wrote `FAIL` aborts the script. All
# other workers had a chance to complete first (so the user sees the
# full picture before the abort).
[[ "${#failed[@]}" -eq 0 ]] || exit 1
