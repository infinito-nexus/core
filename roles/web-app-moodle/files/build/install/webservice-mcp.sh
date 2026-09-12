#!/bin/bash
set -euxo pipefail

: "${MOODLE_SOURCE_DIR:?required}"
: "${MOODLE_WEBSERVICE_SUBDIR:?required}"
: "${MOODLE_MCP_PLUGIN_RELPATH:?required}"
: "${MOODLE_MCP_PLUGIN_ARCHIVE_URL:?required}"

PLUGIN_DIR="${MOODLE_SOURCE_DIR}/${MOODLE_MCP_PLUGIN_RELPATH}"
ZIP_PATH="$(mktemp -t webservice-mcp.XXXXXX.zip)"
EXTRACT_DIR="$(mktemp -d -t webservice-mcp-extract.XXXXXX)"
trap 'rm -rf "${ZIP_PATH}" "${EXTRACT_DIR}"' EXIT

test -d "${MOODLE_SOURCE_DIR}/${MOODLE_WEBSERVICE_SUBDIR}"

curl --connect-timeout 5 --max-time 300 --retry 3 --retry-all-errors --retry-delay 2 -fSL -o "${ZIP_PATH}" "${MOODLE_MCP_PLUGIN_ARCHIVE_URL}"
unzip -q "${ZIP_PATH}" -d "${EXTRACT_DIR}"
rm -rf "${PLUGIN_DIR}"

SRC="$(find "${EXTRACT_DIR}" -maxdepth 1 -type d -name 'moodle-webservice_mcp-*' | sort | head -n1)"
[ -n "${SRC}" ] || { echo "webservice_mcp unpack produced no directory" >&2; exit 1; }

mv "${SRC}" "${PLUGIN_DIR}"
