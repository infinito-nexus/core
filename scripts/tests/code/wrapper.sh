#!/usr/bin/env bash
# Chooses where to execute a test runner based on INFINITO_TEST_RUNNER:
#   docker (default) -- inside the shared test runner infinito-test-<hash>
#                       (scripts/tests/runner/lib.sh) with this checkout as
#                       working directory; with INFINITO_STACK_NAME set, inside
#                       that stack's infinito container instead.
#   host             -- directly against the host shell/Python.
#
# Param $1: repo-relative path of the runner script to execute.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RUNNER_REL="${1:?usage: wrapper.sh <repo-relative-runner-script>}"
RUN_SCRIPT="${REPO_ROOT}/${RUNNER_REL}"

cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh
# shellcheck source=scripts/meta/compose.sh
source scripts/meta/compose.sh
# shellcheck source=scripts/tests/runner/lib.sh
source scripts/tests/runner/lib.sh

: "${INFINITO_TEST_PATTERN:?INFINITO_TEST_PATTERN must be set}"
: "${INFINITO_TEST_RUNNER:?INFINITO_TEST_RUNNER must be set}"
: "${INFINITO_TEST_TYPE:?INFINITO_TEST_TYPE must be set}" # nocheck: makefile-supplied

if [[ -z "${pytest_workers:-}" ]]; then
	pytest_workers="$(python3 -m utils.tests.workers "${INFINITO_TEST_TYPE}")" || pytest_workers="" # nocheck: makefile-supplied
fi
export pytest_workers

RUN_SCRIPT_IN_CONTAINER="${INFINITO_SRC_DIR}/${RUNNER_REL}"

case "${INFINITO_TEST_RUNNER}" in
docker)
	where="compose stack ${INFINITO_STACK_NAME:-}"
	if [[ -z "${INFINITO_STACK_NAME:-}" ]]; then
		where="shared test runner"
		INFINITO_SRC_DIR="${REPO_ROOT}"
		RUN_SCRIPT_IN_CONTAINER="${RUN_SCRIPT}"
	fi
	echo "============================================================"
	echo ">>> Running ${INFINITO_TEST_TYPE^^} tests in ${INFINITO_DISTRO} container (${where})" # nocheck: makefile-supplied
	echo "============================================================"

	exec_env_args=(
		-e ACT="${ACT:-}"
		-e BASH_ENV="${INFINITO_SRC_DIR}/scripts/meta/env/load.sh"
		-e GITHUB_ACTIONS="${GITHUB_ACTIONS:-}"
		-e GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}"
		-e GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-}"
		-e GITHUB_SHA="${GITHUB_SHA:-}"
		-e INFINITO_TEST_PATTERN="${INFINITO_TEST_PATTERN}"
		-e INFINITO_TEST_TYPE="${INFINITO_TEST_TYPE}" # nocheck: makefile-supplied
		-e lint_scope="${lint_scope:-}"
		-e pytest_workers="${pytest_workers:-}"
		-e test_paths="${test_paths:-}"
	)
	if [[ -z "${INFINITO_STACK_NAME:-}" ]]; then
		infinito_test_runner_exec "${REPO_ROOT}" "${exec_env_args[@]}" -- bash --login "${RUN_SCRIPT_IN_CONTAINER}"
		exit
	fi

	if ! infinito_compose ps -q infinito 2>/dev/null | grep -q .; then
		echo ">>> 'infinito' container not running; starting the stack via 'make compose-up'..."
		exec {lockfd}>"${REPO_ROOT}/.compose-up.lock"
		flock "${lockfd}"
		infinito_compose ps -q infinito 2>/dev/null | grep -q . || "${MAKE:-make}" compose-up
		exec {lockfd}>&-
	fi

	INFINITO_DISTRO="${INFINITO_DISTRO}" \
		infinito_compose exec -T \
		"${exec_env_args[@]}" \
		--workdir "${INFINITO_SRC_DIR}" \
		infinito \
		bash --login "${RUN_SCRIPT_IN_CONTAINER}"
	;;
host)
	echo "============================================================"
	echo ">>> Running ${INFINITO_TEST_TYPE^^} tests on host" # nocheck: makefile-supplied
	echo "============================================================"
	exec bash --login "${RUN_SCRIPT}"
	;;
*)
	echo "scripts/tests/code/wrapper.sh: unknown INFINITO_TEST_RUNNER='${INFINITO_TEST_RUNNER}' (expected: docker|host)" >&2 # nocheck: self-path-reference
	exit 2
	;;
esac
