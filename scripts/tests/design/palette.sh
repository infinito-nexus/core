#!/usr/bin/env bash
# Run the design assertions of one deployed app with another base color and
# put the base of the inventory back afterwards, also when a step fails.
#
# Param app: deployed application id (required).
# Param base: hex base color for the check, e.g. '#001f3f' (required).
# Param sync: `design` re-renders the static design files, `role` re-runs the app role for values it bakes at deploy time (required).
# Param variant: matrix round index the app was deployed with (optional).
set -euo pipefail

: "${app:?app=<application_id> required}"
: "${base:?base=<hex> required}"
: "${sync:?sync=<design|role> required}"

case "${sync}" in
design | role) ;;
*)
	echo "sync must be 'design' or 'role', got '${sync}'" >&2
	exit 2
	;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"

render() {
	if [[ "${sync}" == design ]]; then
		app="${app}" variant="${variant:-}" base="${1}" bash scripts/tests/design/sync.sh
	else
		role="${app}" variant="${variant:-}" base="${1}" bash scripts/tests/deploy/local/sync/role.sh
	fi
}

restore() {
	render "" || {
		echo "restore failed: the stack still renders base ${base}" >&2
		exit 1
	}
}

trap restore EXIT
render "${base}"
cmd="bash scripts/tests/e2e/rerun-spec.sh '${app}' --grep design: --grep-invert gallery --retries=0" \
	bash scripts/tests/deploy/local/exec/container.sh
