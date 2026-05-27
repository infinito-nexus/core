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

# Pull project-wide defaults (INFINITO_SRC_DIR, INFINITO_TEST_PATTERN, ...)
# from the generated `.env` (single source of truth) before validating
# anything else, so the :?-checks below see the static defaults.
cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

: "${INFINITO_TEST_PATTERN:?INFINITO_TEST_PATTERN must be set}"
: "${INFINITO_TEST_RUNNER:?INFINITO_TEST_RUNNER must be set}"
: "${INFINITO_TEST_TYPE:?INFINITO_TEST_TYPE must be set}" # nocheck: makefile-supplied

RUN_SCRIPT_IN_CONTAINER="${INFINITO_SRC_DIR}/scripts/tests/code/run.sh"

case "${INFINITO_TEST_RUNNER}" in
docker)
	# INFINITO_DISTRO is sourced (with a `debian` default) from
	# scripts/meta/env/load.sh above, so no explicit check here.
	echo "============================================================"
	echo ">>> Running ${INFINITO_TEST_TYPE^^} tests in ${INFINITO_DISTRO} container (compose stack)" # nocheck: makefile-supplied
	echo "============================================================"

	# Auto-bring-up: if the `infinito` container is not running, kick off
	# `make compose-up` first so test-* doesn't fail with "service not running".
	if ! docker compose ps -q infinito 2>/dev/null | grep -q .; then
		echo ">>> 'infinito' container not running; starting the stack via 'make compose-up'..."
		"${MAKE:-make}" compose-up
	fi

	# Compose auto-loads `.env` (the SPOT generated from default.env),
	# which carries every INFINITO_* default (INFINITO_DNS_IP, INFINITO_IP4,
	# INFINITO_DOMAIN, INFINITO_CONTAINER, INFINITO_SUBNET, ...).
	# BASH_ENV makes `bash --login` source load.sh on startup, pulling
	# every INFINITO_* key from the bind-mounted .env into the test
	# runner's environment (notably INFINITO_WORKER_FETCH, otherwise the
	# external URL probe collapses to 1 worker).
	# Per-invocation env passed through docker exec. Built as a bash
	# array so the inline `# nocheck:` markers between elements stay
	# syntactically valid (a backslash-continued line cannot host an
	# inline comment).
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
