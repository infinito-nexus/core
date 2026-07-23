#!/usr/bin/env bash
# Runs the test suite picked by INFINITO_TEST_TYPE / INFINITO_TEST_PATTERN:
# parallel via pytest-xdist when pytest and xdist are importable, serial
# unittest discover otherwise. Invoked either directly on the host or
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
bash "$(dirname "${BASH_SOURCE[0]}")/../../install/dev-extras.sh" || echo "dev extras install failed; running serial" >&2
_suite_dir="tests/${INFINITO_TEST_TYPE}"                     # nocheck: makefile-supplied
_junit_report="build/test-reports/${INFINITO_TEST_TYPE}.xml" # nocheck: makefile-supplied
if "${PYTHON}" -c 'import pytest, xdist' >/dev/null 2>&1; then
	# Exception: consider_namespace_packages + importlib import mode are
	# required for hyphenated tests/unit/roles/<role>/ dirs; pytest's default
	# identifier walk-up collapses every role's filter_plugins/files package
	# onto one top-level name and cross-imports the wrong module.
	# python_functions= pins collection to unittest-style TestCase methods,
	# the exact set `unittest discover` runs. PYTHONDONTWRITEBYTECODE keeps
	# namespace probing from dropping __pycache__ into roles/.
	mkdir -p build/test-reports
	PYTHONDONTWRITEBYTECODE=1 "${PYTHON}" -m pytest "${_suite_dir}" -q -n auto -rP -p no:cacheprovider \
		--import-mode=importlib \
		--junitxml="${_junit_report}" \
		-o consider_namespace_packages=true \
		-o "norecursedirs=.* *.egg dist node_modules venv" \
		-o python_functions= \
		-o "python_files=${INFINITO_TEST_PATTERN}"
else
	"${PYTHON}" -m unittest discover -s "${_suite_dir}" -t . -p "${INFINITO_TEST_PATTERN}"
fi
