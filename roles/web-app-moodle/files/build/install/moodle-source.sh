#!/bin/bash
# Fetch + extract Moodle source into ${MOODLE_SOURCE_DIR}. The
# entrypoint copies this into the persistent code volume on first
# container start. All values are env vars exported by the Dockerfile
# (single source of truth: roles/web-app-moodle/vars/main.yml).
set -euxo pipefail

: "${MOODLE_CODE_DIR:?required}"
: "${MOODLE_DATA_DIR:?required}"
: "${MOODLE_SOURCE_DIR:?required}"
: "${MOODLE_RUNTIME_USER:?required}"
: "${MOODLE_TARBALL_URL:?required}"
: "${MOODLE_TARBALL_FILENAME:?required}"
: "${MOODLE_VERSION_FILE:?required}"
: "${MOODLE_AUTH_SUBDIR:?required}"

EXTRACT_DIR="$(mktemp -d -t moodle-extract.XXXXXX)"
TARBALL_PATH="$(mktemp -t moodle-tarball.XXXXXX)"
trap 'rm -rf "${EXTRACT_DIR}" "${TARBALL_PATH}"' EXIT

curl --connect-timeout 5 --max-time 600 -fSL -o "${TARBALL_PATH}" "${MOODLE_TARBALL_URL}"
file "${TARBALL_PATH}"

rm -rf "${MOODLE_SOURCE_DIR}"
mkdir -p "${MOODLE_SOURCE_DIR}"
tar -xzf "${TARBALL_PATH}" -C "${EXTRACT_DIR}"
cp -a "${EXTRACT_DIR}/moodle/." "${MOODLE_SOURCE_DIR}/"

test -d "${MOODLE_SOURCE_DIR}/${MOODLE_AUTH_SUBDIR}"
test -f "${MOODLE_SOURCE_DIR}/${MOODLE_VERSION_FILE}"

mkdir -p "${MOODLE_CODE_DIR}" "${MOODLE_DATA_DIR}"
chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" \
  "${MOODLE_SOURCE_DIR}" "${MOODLE_CODE_DIR}" "${MOODLE_DATA_DIR}"
find "${MOODLE_SOURCE_DIR}" -type d -exec chmod 755 {} \;
find "${MOODLE_SOURCE_DIR}" -type f -exec chmod 644 {} \;
