#!/bin/bash
# Install the Catalyst tool_objectfs plugin. All values come from env vars
# exported by the Dockerfile (single source of truth:
# roles/web-app-moodle/vars/main.yml).
set -euxo pipefail

: "${MOODLE_SOURCE_DIR:?required}"
: "${MOODLE_OBJECTFS_PLUGIN_RELPATH:?required}"
: "${MOODLE_OBJECTFS_PLUGIN_ARCHIVE_URL:?required}"
: "${MOODLE_ADMIN_TOOL_SUBDIR:?required}"
: "${MOODLE_OBJECTFS_PATCH_PATH:?required}"

PLUGIN_DIR="${MOODLE_SOURCE_DIR}/${MOODLE_OBJECTFS_PLUGIN_RELPATH}"
ZIP_PATH="$(mktemp -t tool-objectfs.XXXXXX.zip)"
EXTRACT_DIR="$(mktemp -d -t tool-objectfs-extract.XXXXXX)"
trap 'rm -rf "${ZIP_PATH}" "${EXTRACT_DIR}"' EXIT

test -d "${MOODLE_SOURCE_DIR}/${MOODLE_ADMIN_TOOL_SUBDIR}"

curl --connect-timeout 5 --max-time 300 --retry 3 --retry-all-errors --retry-delay 2 -fSL -o "${ZIP_PATH}" "${MOODLE_OBJECTFS_PLUGIN_ARCHIVE_URL}"
unzip -q "${ZIP_PATH}" -d "${EXTRACT_DIR}"
rm -rf "${PLUGIN_DIR}"

SRC="$(find "${EXTRACT_DIR}" -maxdepth 1 -type d -name 'moodle-tool_objectfs-*' | sort | head -n1)"
[ -n "${SRC}" ] || { echo "tool_objectfs unpack produced no directory" >&2; exit 1; }

mv "${SRC}" "${PLUGIN_DIR}"

S3_CLIENT="${PLUGIN_DIR}/classes/local/store/s3/client.php"
if grep -q "use_path_style_endpoint" "${S3_CLIENT}"; then
  echo "tool_objectfs now sets use_path_style_endpoint itself; drop the patch" >&2
  exit 1
fi
patch -p1 -F0 -d "${PLUGIN_DIR}" <"${MOODLE_OBJECTFS_PATCH_PATH}"
grep -q "use_path_style_endpoint" "${S3_CLIENT}"
