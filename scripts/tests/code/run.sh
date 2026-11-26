#!/usr/bin/env bash
# Runs the test suite picked by INFINITO_TEST_TYPE / INFINITO_TEST_PATTERN:
# parallel via pytest-xdist when pytest and xdist are importable, serial
# unittest discover otherwise. Invoked either directly on the host or
# inside the infinito compose container by scripts/tests/code/wrapper.sh
# -- the body is identical for both runners.
#
# Param test_paths: optional space-separated test files run instead of the
#                   whole suite directory (make lint-file, make lint-role).
# Param pytest_workers: optional pytest-xdist worker count (make test-session);
#                       empty means one worker per CPU.
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
read -r -a _targets <<<"${test_paths:-${_suite_dir}}"
if "${PYTHON}" -c 'import pytest, xdist' >/dev/null 2>&1; then
	mkdir -p build/test-reports
	if [[ "${INFINITO_RUNNING_ON_GITHUB}" == "true" ]]; then
		export PYTHONDONTWRITEBYTECODE=1
	else
		PYTHONPYCACHEPREFIX="${PWD}/build/pycache-$(id -u)/${INFINITO_TEST_TYPE}" # nocheck: makefile-supplied
		# Exception: /tmp is where Python's tempfile puts scratch files when TMPDIR is unset, so the pruned prefix matches the tests' own scratch root.
		_scratch_root="${TMPDIR:-/tmp}"
		_scratch_root="${_scratch_root%/}"
		case "${PWD}/" in
		"${_scratch_root}/"*) ;;
		*) rm -rf "${PYTHONPYCACHEPREFIX:?}${_scratch_root}" ;;
		esac
		unset _scratch_root
		export PYTHONPYCACHEPREFIX
	fi
	"${PYTHON}" -m pytest "${_targets[@]}" -q -n "${pytest_workers:-auto}" --dist loadscope --no-loadscope-reorder -p utils.tests.pytest.passes -p utils.tests.pytest.longest_first -p no:cacheprovider \
		--import-mode=importlib \
		--junitxml="${_junit_report}" \
		-o consider_namespace_packages=true \
		-o "norecursedirs=.* *.egg dist node_modules venv" \
		-o python_functions= \
		-o "python_files=${INFINITO_TEST_PATTERN}"
elif [ -n "${test_paths:-}" ]; then
	"${PYTHON}" -m unittest "${_targets[@]}"
else
	"${PYTHON}" -m unittest discover -s "${_suite_dir}" -t . -p "${INFINITO_TEST_PATTERN}"
fi
