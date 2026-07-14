#!/bin/bash
# Install Microsoft auth_oidc plugin pinned to the highest tag matching
# the Moodle major.minor we are building. All values come from env
# vars exported by the Dockerfile (single source of truth:
# roles/web-app-moodle/vars/main.yml).
set -euxo pipefail

: "${MOODLE_SOURCE_DIR:?required}"
: "${MOODLE_OIDC_PLUGIN_RELPATH:?required}"
: "${MOODLE_RELEASE:?required}"
: "${MOODLE_AUTH_SUBDIR:?required}"

MOODLE_VER="$(printf '%s' "${MOODLE_RELEASE}" | sed -E 's/^([0-9]+\.[0-9]+).*/\1/')"

PLUGIN_DIR="${MOODLE_SOURCE_DIR}/${MOODLE_OIDC_PLUGIN_RELPATH}"
ZIP_PATH="$(mktemp -t auth-oidc.XXXXXX.zip)"
EXTRACT_DIR="$(mktemp -d -t auth-oidc-extract.XXXXXX)"
trap 'rm -rf "${ZIP_PATH}" "${EXTRACT_DIR}"' EXIT

VERSION="$(curl --connect-timeout 5 --max-time 60 -sfSL https://api.github.com/repos/microsoft/moodle-auth_oidc/tags \
  | jq -r '.[].name' \
  | grep -E "^v${MOODLE_VER}\." \
  | sort -Vr \
  | head -n1)"

[ -n "${VERSION}" ] || { echo "no auth_oidc tag found for Moodle ${MOODLE_VER}" >&2; exit 1; }

echo "Installing auth_oidc ${VERSION} (Moodle ${MOODLE_VER})"
test -d "${MOODLE_SOURCE_DIR}/${MOODLE_AUTH_SUBDIR}"

curl --connect-timeout 5 --max-time 300 -fSL -o "${ZIP_PATH}" "https://github.com/microsoft/moodle-auth_oidc/archive/refs/tags/${VERSION}.zip"
unzip -q "${ZIP_PATH}" -d "${EXTRACT_DIR}"
rm -rf "${PLUGIN_DIR}"

SRC="$(find "${EXTRACT_DIR}" -maxdepth 1 -type d -name 'moodle-auth_oidc-*' | sort | head -n1)"
[ -n "${SRC}" ] || { echo "auth_oidc unpack produced no directory" >&2; exit 1; }

mv "${SRC}" "${PLUGIN_DIR}"
