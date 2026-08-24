#!/usr/bin/env bash
# shellcheck shell=bash
#
# Runs the Ruby unit suite through minitest, which ships with Ruby itself.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"

bash scripts/install/ruby.sh

suite="tests/unit/ruby"

mapfile -t tests < <(find "${suite}" -name '*_test.rb' | sort)

if ((${#tests[@]} == 0)); then
	printf 'ERROR test-unit-ruby: no Ruby unit tests in %s\n' "${suite}" >&2
	exit 1
fi

export INFINITO_JUNIT_REPORT="${REPO_ROOT}/build/test-reports/${INFINITO_TEST_TYPE:?INFINITO_TEST_TYPE must be set}.xml" # nocheck: makefile-supplied

exec ruby -I"${suite}" -r"${REPO_ROOT}/tests/utils/minitest_junit.rb" \
	-e 'ARGV.each { |f| require File.expand_path(f) }' "${tests[@]}"
