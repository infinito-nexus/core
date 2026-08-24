#!/usr/bin/env bash
# shellcheck shell=bash
#
# Runs the JavaScript unit suite through node:test, Node's built-in runner.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"

bash scripts/install/node.sh

suite="tests/unit/javascript"

mapfile -t tests < <(find "${suite}" -name '*.test.js' | sort)

if ((${#tests[@]} == 0)); then
	printf 'ERROR test-unit-javascript: no JavaScript unit tests in %s\n' "${suite}" >&2
	exit 1
fi

junit_report="build/test-reports/${INFINITO_TEST_TYPE:?INFINITO_TEST_TYPE must be set}.xml" # nocheck: makefile-supplied
mkdir -p build/test-reports

exec node --test \
	--test-reporter=spec --test-reporter-destination=stdout \
	--test-reporter=junit --test-reporter-destination="${junit_report}" \
	"${tests[@]}"
