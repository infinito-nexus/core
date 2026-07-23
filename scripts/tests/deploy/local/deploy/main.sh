#!/usr/bin/env bash
set -euo pipefail

# Single entry point for every local deploy flow.
#
# Routing environment variables (set them via `make compose-deploy<short>=<value>`;
# `make compose-deploy` maps the short Make variables to the INFINITO_* env vars):
#   mode        initialize (default) | reinstall | update | migration
#                               Short Make alias: mode. `migration` runs the
#                               opt-in mail-provider migration scenario
#                               (see apps/migration/selection.sh) and needs
#                               INFINITO_TEST_MIGRATION=true.
#   bundles            optional. Comma-separated bundle names. When
#                               set, routes to bundles/fresh.sh (initialize
#                               or reinstall) or bundles/update.sh (update).
#                               apps is ignored in this case (it
#                               gets resolved from the bundles).
#   apps               optional. Comma-separated app ids. When set
#                               (and bundles is not), routes to the
#                               selection.sh of the chosen verb.
#                               Short Make alias: apps
#   purge     true | false (default: false). When true and
#                               apps is set, runs the entity purge
#                               before the deploy.
#                               Short Make alias: purge

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
cd "${REPO_ROOT}"

MODE="${mode:-initialize}" # nocheck: deploy router knob; routes to apps/<verb>/ subscripts
PURGE="${purge:-false}"    # nocheck: deploy router knob; gates entity pre-purge

case "${MODE}" in
initialize | reinstall | update | migration) ;;
*)
	echo "ERROR: invalid mode='${MODE}' (must be initialize|reinstall|update|migration)" >&2
	exit 2
	;;
esac

# Self-contained scenario: fixed app set, ignores apps/bundles routing.
if [[ "${MODE}" == "migration" ]]; then
	exec bash "${SCRIPT_DIR}/apps/migration/selection.sh"
fi

run_pre_purge() {
	if [[ "${PURGE}" == "true" ]]; then
		echo ">>> Pre-purging entities for apps=${apps}"
		bash scripts/tests/deploy/local/purge/entity.sh
	fi
}

if [[ -n "${bundles:-}" ]]; then
	case "${MODE}" in
	initialize | reinstall)
		target="${SCRIPT_DIR}/bundles/fresh.sh"
		;;
	update)
		target="${SCRIPT_DIR}/bundles/update.sh"
		;;
	esac
elif [[ -n "${apps:-}" ]]; then
	case "${MODE}" in
	initialize)
		run_pre_purge
		exec bash "${SCRIPT_DIR}/apps/initialize/selection.sh" "${apps}"
		;;
	reinstall)
		run_pre_purge
		target="${SCRIPT_DIR}/apps/reinstall/selection.sh"
		;;
	update)
		run_pre_purge
		target="${SCRIPT_DIR}/apps/update/selection.sh"
		;;
	esac
else
	case "${MODE}" in
	initialize)
		echo "=== local full deploy (distro=${INFINITO_DISTRO}) ==="
		target="${SCRIPT_DIR}/apps/initialize/all.sh"
		;;
	reinstall)
		echo "ERROR: mode=reinstall requires apps= or bundles=" >&2
		exit 2
		;;
	update)
		target="${SCRIPT_DIR}/apps/update/all.sh"
		;;
	esac
fi

exec bash "${target}"
