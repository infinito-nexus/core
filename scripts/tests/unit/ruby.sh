#!/usr/bin/env bash
# shellcheck shell=bash
#
# Runs the Ruby unit suite through minitest, which ships with Ruby itself.
#
# minitest/autorun has no directory runner, so the suite files are required
# explicitly and minitest's at_exit hook runs them.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"

suite="tests/unit/ruby"

if [[ -z "$(find "${suite}" -name '*_test.rb' 2>/dev/null)" ]]; then
	printf 'SKIP test-unit-ruby: no Ruby unit tests in %s (see lint mirrored-unit-test)\n' "${suite}"
	exit 0
fi

if ! command -v ruby >/dev/null 2>&1; then
	printf 'SKIP test-unit-ruby: ruby is not installed on this machine\n'
	exit 0
fi

exec ruby -I"${suite}" -e 'Dir.glob("'"${suite}"'/**/*_test.rb").each { |f| require File.expand_path(f) }'
