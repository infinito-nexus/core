#!/usr/bin/env bash
set -euo pipefail

# Local app test without teardown/cleanup.
# Usage:
#   scripts/tests/deploy/local/deploy/fresh-kept-app.sh <app-id>
#
# Environment variables:
#   INFINITO_DISTRO   arch|debian|ubuntu|fedora|centos (default from scripts/meta/env/all.sh)
#   INVENTORY_DIR     target inventory dir (default from scripts/meta/env/all.sh)
#   LIMIT_HOST        host limit (default: localhost)
#   DEBUG             true|false (default: true)
#
# Examples:
#   scripts/tests/deploy/local/deploy/fresh-kept-app.sh web-app-mailu
#   INFINITO_DISTRO=arch DEBUG=false scripts/tests/deploy/local/deploy/fresh-kept-app.sh web-app-nextcloud

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

# shellcheck source=scripts/tests/deploy/local/utils/lib.sh
source "${SCRIPT_DIR}/../utils/lib.sh"

cd "${REPO_ROOT}"

if [[ -f "scripts/meta/env/all.sh" ]]; then
	# shellcheck source=scripts/meta/env/all.sh
	source "scripts/meta/env/all.sh"
else
	echo "ERROR: missing scripts/meta/env/all.sh" >&2
	exit 2
fi

: "${PYTHON:=python3}"

usage() {
	cat <<'EOF'
Usage:
  fresh-kept-app.sh <app-id>

ENV:
  INFINITO_DISTRO=<arch|debian|ubuntu|fedora|centos>
  INVENTORY_DIR=<path>
  LIMIT_HOST=<host-pattern>
  DEBUG=<true|false>
  -h, --help
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -eq 0 ]]; then
	usage
	exit 0
fi

APPS="${1:-}"
shift

if [[ -z "${APPS}" ]]; then
	echo "ERROR: app-id is required" >&2
	usage
	exit 2
fi

if [[ $# -gt 0 ]]; then
	echo "ERROR: unknown argument(s): $*" >&2
	echo "Pass config via ENV (INFINITO_DISTRO, INVENTORY_DIR, LIMIT_HOST, DEBUG)." >&2
	usage
	exit 2
fi

# INFINITO_DISTRO is set by scripts/meta/env/defaults.sh (single SPOT,
# defaults to debian) — no local fallback here.
INVENTORY_DIR="${INVENTORY_DIR:-}"
LIMIT_HOST="${LIMIT_HOST:-localhost}"

if [[ -z "${INVENTORY_DIR}" ]]; then
	echo "ERROR: INVENTORY_DIR is empty after loading scripts/meta/env/all.sh" >&2
	exit 2
fi

case "${INFINITO_DISTRO}" in
arch | debian | ubuntu | fedora | centos) ;;
*)
	echo "ERROR: invalid distro '${INFINITO_DISTRO}'" >&2
	exit 2
	;;
esac

DEBUG="$(normalize_bool_or_default "${DEBUG:-}" true DEBUG)"

echo "=== local app test (no cleanup) ==="
echo "app ids       = ${APPS}"
echo "distro        = ${INFINITO_DISTRO}"
echo "inventory_dir = ${INVENTORY_DIR}"
echo "limit         = ${LIMIT_HOST}"
echo "debug         = ${DEBUG}"
echo

echo ">>> Ensuring development stack is up (when-down)"
"${PYTHON}" -m cli.deploy.development up \
	--when-down

echo ">>> Running entry.sh bootstrap inside container"
"${PYTHON}" -m cli.deploy.development exec \
	-- bash /opt/src/infinito/scripts/tests/deploy/local/utils/entry-bootstrap.sh

echo ">>> Creating inventory for app '${APPS}'"
"${PYTHON}" -m cli.deploy.development init \
	--apps "${APPS}" \
	--inventory-dir "${INVENTORY_DIR}" \
	--vars '{"ASYNC_ENABLED": false}'

deploy_cmd=(
	"${PYTHON}" -m cli.deploy.development deploy
	--apps "${APPS}"
	--inventory-dir "${INVENTORY_DIR}"
)

if [[ "${DEBUG}" == "true" ]]; then
	deploy_cmd+=(--debug)
fi

# NOTE: --skip-cleanup keeps cleanup routines disabled during this local test run.
deploy_cmd+=(-- --skip-backup --skip-cleanup --limit "${LIMIT_HOST}")

echo ">>> Deploying app '${APPS}'"
"${deploy_cmd[@]}"

echo
echo "✅ Finished. Stack and inventory remain on disk (no teardown)."
