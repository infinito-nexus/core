#!/usr/bin/env bash
set -euo pipefail

# Resolve effective workflow parameters (STRICT MODE)
#
# Required:
#   INFINITO_DEPLOY_TYPE   (server|workstation|universal)
#   INFINITO_DISTROS            (space-separated distro list, e.g. "arch debian")
#
# Always defined:
#   INFINITO_WHITELIST (may be empty, but will always be set)
#
# Provided either via:
#   - act --env
#   - workflow_dispatch inputs (forwarded as INPUT_*)
#
# Writes:
#   - to $GITHUB_OUTPUT: test_deploy_type, distros, whitelist
#   - to $GITHUB_ENV:   INFINITO_DEPLOY_TYPE, INFINITO_DISTROS, INFINITO_WHITELIST

: "${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set (running inside GitHub Actions or act)}"
: "${GITHUB_ENV:?GITHUB_ENV must be set (running inside GitHub Actions or act)}"

# Priority:
#   1) real env
#   2) workflow inputs (passed via env by workflow step)
# Script runs in GHA workflow context where .env is not loaded; the INPUT_* fallback IS the SPOT here.
INFINITO_DEPLOY_TYPE="${INFINITO_DEPLOY_TYPE:-${INPUT_TEST_DEPLOY_TYPE:-}}" # nocheck: gha-input-bridge
INFINITO_DISTROS="${INFINITO_DISTROS:-${INPUT_DISTROS:-}}"                  # nocheck: gha-input-bridge

# INFINITO_WHITELIST must always exist, but may be empty
INFINITO_WHITELIST="${INFINITO_WHITELIST:-${INPUT_WHITELIST:-}}" # nocheck: gha-input-bridge
INFINITO_WHITELIST="${INFINITO_WHITELIST:-}"                     # force defined even if still empty

# Hard requirements
: "${INFINITO_DEPLOY_TYPE:?INFINITO_DEPLOY_TYPE must be set (server|workstation|universal)}"
: "${INFINITO_DISTROS:?INFINITO_DISTROS must be set (e.g. \"arch debian ubuntu\")}"

case "${INFINITO_DEPLOY_TYPE}" in
server | workstation | universal) ;;
*)
	echo "Invalid INFINITO_DEPLOY_TYPE: ${INFINITO_DEPLOY_TYPE}" >&2
	echo "Allowed: server | workstation | universal" >&2
	exit 2
	;;
esac

echo "Resolved inputs:"
echo "  INFINITO_DEPLOY_TYPE=${INFINITO_DEPLOY_TYPE}"
echo "  INFINITO_DISTROS=${INFINITO_DISTROS}"
echo "  INFINITO_WHITELIST=${INFINITO_WHITELIST}"

# Export outputs for workflow
{
	echo "test_deploy_type=${INFINITO_DEPLOY_TYPE}"
	echo "distros=${INFINITO_DISTROS}"
	echo "whitelist=${INFINITO_WHITELIST}"
} >>"${GITHUB_OUTPUT}"

# Export env for subsequent steps
{
	echo "INFINITO_DEPLOY_TYPE=${INFINITO_DEPLOY_TYPE}"
	echo "INFINITO_DISTROS=${INFINITO_DISTROS}"
	echo "INFINITO_WHITELIST=${INFINITO_WHITELIST}"
} >>"${GITHUB_ENV}"
