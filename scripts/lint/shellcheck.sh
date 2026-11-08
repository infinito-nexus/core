#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

# shellcheck source=scripts/lint/diff/files.sh
source "${SCRIPT_DIR}/diff/files.sh"

if lint_diff_active shellcheck; then
	mapfile -t shellcheck_files < <(lint_diff_files '\.sh$')
else
	mapfile -t shellcheck_files < <(find . -type f -name '*.sh' 2>/dev/null | sed 's|^\./||' | sort)
fi
if [[ "${#shellcheck_files[@]}" -eq 0 ]]; then
	printf 'No shell scripts found.\n'
	exit 0
fi

: "${INFINITO_WORKER_CPU:?INFINITO_WORKER_CPU must be set (provided by default.env via the env loader)}"

check() {
	printf '%s\0' "${shellcheck_files[@]}" |
		xargs -0 -n 25 -P "${INFINITO_WORKER_CPU}" shellcheck -x
}

if check; then
	exit 0
fi

diff_file="$(mktemp)"
cleanup() {
	rm -f "${diff_file}"
}
trap cleanup EXIT

set +e
shellcheck -f diff -x "${shellcheck_files[@]}" >"${diff_file}" 2>/dev/null
set -e

if [[ ! -s "${diff_file}" ]]; then
	exit 1
fi

printf 'Applying ShellCheck autofixes.\n'
git apply --whitespace=nowarn "${diff_file}"
check
