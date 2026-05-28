#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

mapfile -t shellcheck_files < <(find . -type f -name '*.sh' \
	-not -path './.venv/*' \
	-not -path './node_modules/*' \
	2>/dev/null | sort)
if [[ "${#shellcheck_files[@]}" -eq 0 ]]; then
	printf 'No shell scripts found.\n'
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

if [[ -s "${diff_file}" ]]; then
	printf 'Applying ShellCheck autofixes.\n'
	git apply --whitespace=nowarn "${diff_file}"
fi

shellcheck -x "${shellcheck_files[@]}"
