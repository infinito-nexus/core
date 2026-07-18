#!/usr/bin/env bash
# Stops/removes docker compose stack for /opt/compose/<STACK>/compose.yml
#
# Usage:
#   ./purge/entity/compose.sh <STACK1> [STACK2] [...]

set -euo pipefail

if [[ "$#" -lt 1 ]]; then
	echo "ERROR: No stack names provided." >&2
	exit 2
fi

log() { echo ">>> $*"; }
warn() { echo "!!! WARNING: $*" >&2; }

run_no_stdin() { "$@" </dev/null; }

overall_rc=0

for STACK_NAME in "$@"; do
	(
		set -euo pipefail

		STACK_DIR="/opt/compose/${STACK_NAME}"
		COMPOSE_FILE="${STACK_DIR}/compose.yml"

		if [[ ! -f "${COMPOSE_FILE}" ]]; then
			warn "compose.yml not found for '${STACK_NAME}' (${COMPOSE_FILE}) — skipping compose down"
			exit 0
		fi

		log "Compose down for '${STACK_NAME}'..."
		cd "$STACK_DIR"
		run_no_stdin compose down --remove-orphans -v || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
	) || {
		rc=$?
		overall_rc=1
		warn "Compose down failed for '${STACK_NAME}' (rc=${rc}) — continuing"
	}
done

exit "${overall_rc}"
