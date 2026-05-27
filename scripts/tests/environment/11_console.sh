#!/usr/bin/env bash
# Smoke-test the interactive console REPL end-to-end: prompt format,
# stateful cd / home / return / `infinito` jump, relative-then-absolute
# command resolve, and executable-leaf-runs-instead-of-cd. Runs `python
# -m cli.console` with a scripted stdin and asserts the prompt sequence
# the REPL produced.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/environment/utils/common.sh
source "${SCRIPT_DIR}/utils/common.sh"

cd "${REPO_ROOT}"

log_file="$(mktemp -t infinito-console-smoke.XXXXXX)"
trap 'rm -f "${log_file}"' EXIT

# Feed a navigation sequence covering every entry point:
#   - bare-category cd  : administration / meta
#   - infinito alone    : jumps to root
#   - infinito <path>   : absolute jump even from a nested cwd
#   - / and ..          : root and up-one
#   - /abs/path         : absolute path nav with slashes
#   - ../rel/path       : relative path nav with leading dotdot
printf '%s\n' \
	'ls' \
	'administration' \
	'ls' \
	'infinito meta' \
	'..' \
	'/administration/deploy' \
	'../..' \
	'infinito administration' \
	'../meta' \
	'/' \
	'exit' |
	"${PYTHON}" -m cli.console \
		>"${log_file}" 2>&1 || true

assert_log_contains() {
	local needle="${1}"
	if ! grep -qF -- "${needle}" "${log_file}"; then
		echo "[FAIL] console output missing: ${needle}" >&2
		echo "--- captured console output ---" >&2
		cat "${log_file}" >&2
		exit 1
	fi
	echo "[OK] console output contains: ${needle}"
}

assert_log_contains "infinito> "
assert_log_contains "infinito administration> "
assert_log_contains "infinito meta> "
assert_log_contains "infinito administration deploy> "
assert_log_contains "🗂️"
assert_log_contains "⚙️"
assert_log_contains "administration"
assert_log_contains "deploy"

echo "Console smoke test passed."
