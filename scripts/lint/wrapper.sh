#!/usr/bin/env bash
# Dispatcher for scripts/lint/<TYPE>.sh based on INFINITO_LINT_RUNNER:
#   host             -- directly on the host shell (tools resolved via PATH).
#   docker           -- inside the running infinito compose container
#                       (requires `make compose-up`; auto-brings the stack up).
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

: "${1:?lint type required (e.g. ansible, python, shellcheck, markdown, action, galaxy, makefile, javascript, autoformat)}"
: "${INFINITO_LINT_RUNNER:?INFINITO_LINT_RUNNER must be set}"

lint_type="$1"
shift
target_script="scripts/lint/${lint_type}.sh"

if [[ ! -f "${target_script}" ]]; then
	echo "scripts/lint/wrapper.sh: unknown lint type '${lint_type}' (no ${target_script})" >&2 # nocheck: self-path-reference
	exit 2
fi

case "${INFINITO_LINT_RUNNER}" in
host)
	exec bash --login "${target_script}" "$@"
	;;
docker)
	# Use bash (not --login) inside the container: --login sources
	# /etc/profile which resets PATH to the Debian system default and
	# drops the image's /opt/venvs/infinito/bin entry, leaving tools
	# like ruff / mbake / ansible-lint undiscoverable. BASH_ENV via -e
	# still sources load.sh on non-interactive bash startup.
	echo "============================================================"
	echo ">>> Running lint '${lint_type}' in ${INFINITO_DISTRO} container (compose stack)"
	echo "============================================================"

	if ! docker compose ps -q infinito 2>/dev/null | grep -q .; then
		echo ">>> 'infinito' container not running; starting the stack via 'make compose-up'..."
		"${MAKE:-make}" compose-up
	fi

	# Pass BASH_ENV so `bash --login` auto-sources load.sh inside the
	# container, putting every INFINITO_* key from the bind-mounted .env
	# into the lint script's environment. Without this the script body
	# would see `set -u` unbound-variable errors on first ${INFINITO_X}.
	INFINITO_DISTRO="${INFINITO_DISTRO}" \
		docker compose exec -T \
		-e ACT="${ACT:-}" \
		-e BASH_ENV="${INFINITO_SRC_DIR}/scripts/meta/env/load.sh" \
		-e GITHUB_ACTIONS="${GITHUB_ACTIONS:-}" \
		-e GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}" \
		-e GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-}" \
		-e GITHUB_SHA="${GITHUB_SHA:-}" \
		--workdir "${INFINITO_SRC_DIR}" \
		infinito \
		bash "${INFINITO_SRC_DIR}/${target_script}" "$@"
	;;
*)
	echo "scripts/lint/wrapper.sh: unknown INFINITO_LINT_RUNNER='${INFINITO_LINT_RUNNER}' (expected: host|docker)" >&2 # nocheck: self-path-reference
	exit 2
	;;
esac
