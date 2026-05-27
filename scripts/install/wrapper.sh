#!/usr/bin/env bash
# shellcheck shell=bash
#
# Dispatcher for `python -m utils.install.lint` based on INFINITO_LINT_RUNNER:
#   host             -- install lint tools into the host venv.
#   docker           -- install lint tools inside the running infinito
#                       compose container (requires `make compose-up`; auto-brings
#                       the stack up).
#
# The per-environment stamp (build/install-lint-<hash>.stamp; <hash> is
# of sys.executable) lets host and container track their installs
# independently even though `build/` is bind-mounted.
#
# Argv: forwarded verbatim to `python -m utils.install.lint`
#   (`--force`, group names like `ansible`/`python`/...; see the
#    module's CLI for the full surface).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

: "${INFINITO_LINT_RUNNER:?INFINITO_LINT_RUNNER must be set}"

case "${INFINITO_LINT_RUNNER}" in
host)
	exec python3 -m utils.install.lint "$@"
	;;
docker)
	if ! docker compose ps -q infinito 2>/dev/null | grep -q .; then
		echo ">>> 'infinito' container not running; starting the stack via 'make compose-up'..."
		"${MAKE:-make}" compose-up
	fi

	INFINITO_DISTRO="${INFINITO_DISTRO}" \
		docker compose exec -T \
		-e BASH_ENV="${INFINITO_SRC_DIR}/scripts/meta/env/load.sh" \
		--workdir "${INFINITO_SRC_DIR}" \
		infinito \
		python3 -m utils.install.lint "$@"
	;;
*)
	echo "scripts/install/wrapper.sh: unknown INFINITO_LINT_RUNNER='${INFINITO_LINT_RUNNER}' (expected: host|docker)" >&2 # nocheck: self-path-reference
	exit 2
	;;
esac
