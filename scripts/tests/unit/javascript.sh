#!/usr/bin/env bash
# shellcheck shell=bash
#
# Runs the JavaScript unit suite through node:test, Node's built-in runner.
#
# The glob is quoted so node expands it, not the shell: passing the bare
# directory makes the runner resolve test files as module specifiers and fail
# with MODULE_NOT_FOUND.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"

suite="tests/unit/javascript"

if [[ -z "$(find "${suite}" -name '*.test.js' 2>/dev/null)" ]]; then
	printf 'SKIP test-unit-javascript: no JavaScript unit tests in %s\n' "${suite}"
	exit 0
fi

exec node --test "${suite}/**/*.test.js"
