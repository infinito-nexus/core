#!/usr/bin/env bash
# shellcheck shell=bash
#
# CLI test for dsk-blender: the MCP bridge is installed and every agent the
# host deploys knows it.
#
# Env (rendered into test.env from templates/test.env.j2):
#   BONSAI_EXPECTED      whether the IFC and BIM extension is declared
#   BONSAI_EXTENSION_ID  the id blender lists it under
#   MCP_ADDON_MODULE     the module the saved preferences enable
#   MCP_CLAUDE_EXPECTED  whether dsk-gnt-claude is deployed on this host
#   MCP_CLAUDE_REGISTRY  the user-scope MCP registry claude writes
#   MCP_CODEX_EXPECTED   whether dsk-gnt-codex is deployed on this host
#   MCP_CODE_BINARY      the editor binary of the deployed flavor
#   MCP_CODE_EXPECTED    whether dsk-code is deployed on this host
#   MCP_SERVER_COMMAND   absolute path of the MCP server entry point
#   MCP_SERVER_NAME      the name both clients register it under
#   MCP_USER_HOME        home of the workstation user that owns the bridge
set -euo pipefail

: "${BONSAI_EXPECTED:?}"
: "${BONSAI_EXTENSION_ID?}"
: "${MCP_ADDON_MODULE:?}"
: "${MCP_CLAUDE_EXPECTED:?}"
: "${MCP_CLAUDE_REGISTRY:?}"
: "${MCP_CODEX_EXPECTED:?}"
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

echo "[dsk-blender] the saved preferences enable the add-on"
blender_config="${MCP_USER_HOME}/.config/blender"
flatpak_app=""
flatpak_launcher='/app/([^/]+)/[^/]+/[^/]+/[^/]+/export/bin/([^/]+)$'
launcher="$(realpath "$(command -v blender)")"
if [[ "${launcher}" =~ ${flatpak_launcher} && "${BASH_REMATCH[1]}" == "${BASH_REMATCH[2]}" ]]; then
	flatpak_app="${BASH_REMATCH[1]}"
	blender_config="${MCP_USER_HOME}/.var/app/${flatpak_app}/config/blender"
fi
sandbox_rc=0
if [[ -n "${flatpak_app}" ]]; then
	as_user=()
	if [[ "$(stat -c %u "${MCP_USER_HOME}")" != "${EUID}" ]]; then
		as_user=(runuser -u "$(stat -c %U "${MCP_USER_HOME}")" --)
	fi
	sandbox_out="$("${as_user[@]}" env -C "${MCP_USER_HOME}" HOME="${MCP_USER_HOME}" flatpak run --command=true "${flatpak_app}" 2>&1)" || sandbox_rc=$?
fi
if [[ "${sandbox_rc}" -ne 0 ]]; then
	echo "SKIP: ${flatpak_app} cannot start its Flatpak sandbox, so the role left the add-on disabled (flatpak exited ${sandbox_rc}: ${sandbox_out})"
else
	grep -aqs "${MCP_ADDON_MODULE}" "${blender_config}"/*/config/userpref.blend
fi

if [[ "${MCP_CLAUDE_EXPECTED}" == "true" ]]; then
	echo "[dsk-blender] claude carries the server"
	grep -q "\"${MCP_SERVER_NAME}\"" "${MCP_CLAUDE_REGISTRY}"
fi

if [[ "${MCP_CODEX_EXPECTED}" == "true" ]]; then
	echo "[dsk-blender] codex carries the server"
	python3 -c 'import sys, tomllib; sys.exit(sys.argv[2] not in tomllib.load(open(sys.argv[1], "rb")).get("mcp_servers", {}))' \
		"${MCP_USER_HOME}/.codex/config.toml" "${MCP_SERVER_NAME}"
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
