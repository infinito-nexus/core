#!/usr/bin/env bash
# Runs the actual unittest discover invocation for the test suite picked
# by INFINITO_TEST_TYPE / INFINITO_TEST_PATTERN. Invoked either directly on the host or
# inside the infinito compose container by scripts/tests/code/wrapper.sh
# -- the body is identical for both runners.
set -euo pipefail

_run_sh_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/meta/env/load.sh
source "${_run_sh_dir}/../../meta/env/load.sh"
unset _run_sh_dir

: "${INFINITO_TEST_PATTERN:?INFINITO_TEST_PATTERN must be set}"
: "${INFINITO_TEST_TYPE:?INFINITO_TEST_TYPE must be set}" # nocheck: makefile-supplied

echo "PWD=$(pwd)"
echo "PYTHON=${PYTHON:-<unset>}"

if [ -n "${PYTHON:-}" ]; then
	PATH="$(dirname "$PYTHON"):$PATH"
	export PATH
fi

make setup
"${PYTHON}" -m unittest discover -s "tests/${INFINITO_TEST_TYPE}" -t . -p "${INFINITO_TEST_PATTERN}" # nocheck: makefile-supplied
