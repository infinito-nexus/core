#!/usr/bin/env bash
# shellcheck shell=bash
#
# Runs the PHP unit suite through PHPUnit.
#
# Every shipped PHP file carries a mirrored-unit-test exemption today, so the
# suite is empty and this skips rather than letting PHPUnit fail on "no tests
# executed". An absent interpreter or vendor tree skips loudly for the same
# reason: a machine without PHP must not fail the whole gate.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"

suite="tests/unit/php"

if [[ -z "$(find "${suite}" -name '*Test.php' 2>/dev/null)" ]]; then
	printf 'SKIP test-unit-php: no PHP unit tests in %s (see lint mirrored-unit-test)\n' "${suite}"
	exit 0
fi

if ! command -v php >/dev/null 2>&1; then
	printf 'SKIP test-unit-php: php is not installed on this machine\n'
	exit 0
fi

if [[ ! -x vendor/bin/phpunit ]]; then
	printf "SKIP test-unit-php: run 'composer install' first\n"
	exit 0
fi

exec vendor/bin/phpunit
