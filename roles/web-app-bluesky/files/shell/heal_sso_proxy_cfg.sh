#!/usr/bin/env bash
# Remove the oauth2-proxy cfg bind-mount source when a prior deploy left it as a directory.
#
# Environment:
#   SSO_PROXY_CFG_PATH   host path the oauth2-proxy cfg file is bind-mounted from
#   SSO_PROXY_CONTAINER  container that mounts it, stopped before the removal
set -euo pipefail

cfg_path="${SSO_PROXY_CFG_PATH:?SSO_PROXY_CFG_PATH must be set}"
container_name="${SSO_PROXY_CONTAINER:?SSO_PROXY_CONTAINER must be set}"

if [[ -d "${cfg_path}" ]]; then
	if container inspect "${container_name}" >/dev/null 2>&1; then
		container stop "${container_name}" >/dev/null
	fi
	rm -rf "${cfg_path}"
fi
