#!/usr/bin/env bash
# Chooses where to execute scripts/tests/code/run.sh based on
# INFINITO_TEST_RUNNER:
#   docker (default) -- inside the already-running infinito compose
#                       container (requires `make compose-up`).
#   host             -- directly against the host shell/Python.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RUN_SCRIPT="${SCRIPT_DIR}/run.sh"

cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

: "${INFINITO_TEST_PATTERN:?INFINITO_TEST_PATTERN must be set}"
: "${INFINITO_TEST_RUNNER:?INFINITO_TEST_RUNNER must be set}"
: "${INFINITO_TEST_TYPE:?INFINITO_TEST_TYPE must be set}" # nocheck: makefile-supplied

RUN_SCRIPT_IN_CONTAINER="${INFINITO_SRC_DIR}/scripts/tests/code/run.sh"

case "${INFINITO_TEST_RUNNER}" in
docker)
	echo "============================================================"
	echo ">>> Running ${INFINITO_TEST_TYPE^^} tests in ${INFINITO_DISTRO} container (compose stack)" # nocheck: makefile-supplied
	echo "============================================================"

	if ! docker compose ps -q infinito 2>/dev/null | grep -q .; then
		echo ">>> 'infinito' container not running; starting the stack via 'make compose-up'..."
		exec {lockfd}>"${REPO_ROOT}/.compose-up.lock"
		flock "${lockfd}"
		docker compose ps -q infinito 2>/dev/null | grep -q . || "${MAKE:-make}" compose-up
		exec {lockfd}>&-
	fi

	exec_env_args=(
		-e ACT="${ACT:-}"
		-e BASH_ENV="${INFINITO_SRC_DIR}/scripts/meta/env/load.sh"
		-e GITHUB_ACTIONS="${GITHUB_ACTIONS:-}"
		-e GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}"
		-e GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-}"
		-e GITHUB_SHA="${GITHUB_SHA:-}"
		-e INFINITO_TEST_PATTERN="${INFINITO_TEST_PATTERN}"
		-e INFINITO_TEST_TYPE="${INFINITO_TEST_TYPE}" # nocheck: makefile-supplied
	)
	INFINITO_DISTRO="${INFINITO_DISTRO}" \
		docker compose exec -T \
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
