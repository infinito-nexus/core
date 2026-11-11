#!/usr/bin/env bash
# Dispatcher for scripts/lint/<TYPE>.sh based on INFINITO_LINT_RUNNER:
#   host             -- directly on the host shell (tools resolved via PATH).
#   docker           -- inside the shared test runner infinito-test-<hash>
#                       (scripts/tests/runner/lib.sh) with this checkout as
#                       working directory; with INFINITO_STACK_NAME set, inside
#                       that stack's infinito container (auto-brings it up).
#
# Argv: <TYPE> [extra args forwarded to the lint script]
#   TYPE is the basename (without `.sh`) of a sibling script next to this
#   one, e.g. `ansible` resolves to scripts/lint/ansible.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh
# shellcheck source=scripts/meta/compose.sh
source scripts/meta/compose.sh
# shellcheck source=scripts/tests/runner/lib.sh
source scripts/tests/runner/lib.sh

: "${1:?lint type required (e.g. ansible, python, shellcheck, markdown, action, galaxy, makefile, javascript, autoformat)}"
: "${INFINITO_LINT_RUNNER:?INFINITO_LINT_RUNNER must be set}"

lint_type="$1"
shift
target_script="scripts/lint/${lint_type}.sh"

if [[ ! -f "${target_script}" ]]; then
	echo "scripts/lint/wrapper.sh: unknown lint type '${lint_type}' (no ${target_script})" >&2 # nocheck: self-path-reference
	exit 2
fi

# shellcheck source=scripts/lint/diff/files.sh
source scripts/lint/diff/files.sh
diff_files="$(lint_diff_write "${lint_type}")"

case "${INFINITO_LINT_RUNNER}" in
host)
	LINT_DIFF_FILES="${diff_files}" exec bash --login "${target_script}" "$@"
	;;
docker)
	where="compose stack ${INFINITO_STACK_NAME:-}"
	if [[ -z "${INFINITO_STACK_NAME:-}" ]]; then
		where="shared test runner"
		INFINITO_SRC_DIR="${REPO_ROOT}"
	fi
	# like ruff / mbake / ansible-lint undiscoverable. BASH_ENV via -e
	echo "============================================================"
	echo ">>> Running lint '${lint_type}' in ${INFINITO_DISTRO} container (${where})"
	echo "============================================================"

	exec_env_args=(
		-e ACT="${ACT:-}"
		-e BASH_ENV="${INFINITO_SRC_DIR}/scripts/meta/env/load.sh"
		-e GITHUB_ACTIONS="${GITHUB_ACTIONS:-}"
		-e GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}"
		-e GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-}"
		-e GITHUB_SHA="${GITHUB_SHA:-}"
		-e LINT_DIFF_FILES="${diff_files}"
	)
	if [[ -z "${INFINITO_STACK_NAME:-}" ]]; then
		infinito_test_runner_exec "${REPO_ROOT}" "${exec_env_args[@]}" -- bash "${INFINITO_SRC_DIR}/${target_script}" "$@"
		exit
	fi

	if ! infinito_compose ps -q infinito 2>/dev/null | grep -q .; then
		echo ">>> 'infinito' container not running; starting the stack via 'make compose-up'..."
		"${MAKE:-make}" compose-up
	fi

	INFINITO_DISTRO="${INFINITO_DISTRO}" \
		infinito_compose exec -T \
		"${exec_env_args[@]}" \
		--workdir "${INFINITO_SRC_DIR}" \
		infinito \
		bash "${INFINITO_SRC_DIR}/${target_script}" "$@"
	;;
*)
	echo "scripts/lint/wrapper.sh: unknown INFINITO_LINT_RUNNER='${INFINITO_LINT_RUNNER}' (expected: host|docker)" >&2 # nocheck: self-path-reference
	exit 2
	;;
esac
