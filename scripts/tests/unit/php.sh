#!/usr/bin/env bash
# shellcheck shell=bash
#
# Runs the PHP unit suite through PHPUnit.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"

bash scripts/install/php.sh

junit_report="build/test-reports/${INFINITO_TEST_TYPE:?INFINITO_TEST_TYPE must be set}.xml" # nocheck: makefile-supplied
mkdir -p build/test-reports

exec vendor/bin/phpunit --log-junit "${junit_report}"
