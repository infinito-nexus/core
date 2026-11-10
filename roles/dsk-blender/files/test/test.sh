#!/usr/bin/env bash
# shellcheck shell=bash
#
# CLI test for dsk-blender: the MCP bridge is installed and every agent the
# host deploys knows it.
#
# Env (rendered into test.env from templates/test.env.j2):
#   BONSAI_EXPECTED      whether the IFC and BIM extension is declared
#   BONSAI_EXTENSION_ID  the id blender lists it under
#   MCP_CLAUDE_EXPECTED  whether dsk-gnt-claude is deployed on this host
#   MCP_CLAUDE_REGISTRY  the user-scope MCP registry claude writes
#   MCP_CODE_BINARY      the editor binary of the deployed flavor
#   MCP_CODE_EXPECTED    whether dsk-code is deployed on this host
#   MCP_SERVER_COMMAND   absolute path of the MCP server entry point
#   MCP_SERVER_NAME      the name both clients register it under
#   MCP_USER_HOME        home of the workstation user that owns the bridge
set -euo pipefail

: "${BONSAI_EXPECTED:?}"
: "${BONSAI_EXTENSION_ID?}"
: "${MCP_CLAUDE_EXPECTED:?}"
: "${MCP_CLAUDE_REGISTRY:?}"
: "${MCP_CODE_BINARY?}"
: "${MCP_CODE_EXPECTED:?}"
: "${MCP_SERVER_COMMAND:?}"
: "${MCP_SERVER_NAME:?}"
: "${MCP_USER_HOME:?}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[dsk-blender] the server command resolves"
command -v "${MCP_SERVER_COMMAND}"

echo "[dsk-blender] the server completes an MCP initialize handshake"
served="$(python3 "${here}/initialize.py" "${MCP_SERVER_COMMAND}")"
echo "[dsk-blender] served by: ${served}"

if [[ "${MCP_CLAUDE_EXPECTED}" == "true" ]]; then
	echo "[dsk-blender] claude carries the server"
	grep -q "\"${MCP_SERVER_NAME}\"" "${MCP_CLAUDE_REGISTRY}"
fi

if [[ "${MCP_CODE_EXPECTED}" == "true" ]] && command -v "${MCP_CODE_BINARY}" >/dev/null; then
	echo "[dsk-blender] the editor carries the server"
	grep -rqs "\"${MCP_SERVER_NAME}\"" \
		"${MCP_USER_HOME}/.config/Code - OSS/User/mcp.json" \
		"${MCP_USER_HOME}/.config/Code/User/mcp.json" \
		"${MCP_USER_HOME}/.config/VSCodium/User/mcp.json"
fi

if [[ "${BONSAI_EXPECTED}" == "true" ]]; then
	echo "[dsk-blender] blender carries the IFC and BIM extension"
	blender --command extension list | grep -q "${BONSAI_EXTENSION_ID}"
fi

echo "[dsk-blender] OK"
