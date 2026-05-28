#!/usr/bin/env bash
set -euo pipefail

# Run local deploy workflow via act for a single app (linear matrix)
# Required:
#   apps    e.g. web-app-nextcloud
#   INFINITO_DEPLOY_TYPE server|workstation|universal
#   INFINITO_DISTRO  e.g. arch, debian, ubuntu

: "${apps:?apps is not set (e.g. apps=web-app-nextcloud)}"
: "${INFINITO_DEPLOY_TYPE:?INFINITO_DEPLOY_TYPE is not set (server|workstation|universal)}"
: "${INFINITO_DISTRO:?INFINITO_DISTRO is not set (e.g. arch, debian, ubuntu)}"

case "${INFINITO_DEPLOY_TYPE}" in
server | workstation | universal) ;;
*)
	echo "Invalid INFINITO_DEPLOY_TYPE: ${INFINITO_DEPLOY_TYPE}" >&2
	echo "Allowed: server | workstation | universal" >&2
	exit 2
	;;
esac

echo "=== act: deploy local (type=${INFINITO_DEPLOY_TYPE}, app=${apps}, distros=${INFINITO_DISTRO}) ==="

act workflow_dispatch \
	-W .github/workflows/test-deploy-local.yml \
	--input test_deploy_type="${INFINITO_DEPLOY_TYPE}" \
	--input distros="${INFINITO_DISTRO}" \
	--input whitelist="${apps}" \
	--container-options "--privileged" \
	--network host
