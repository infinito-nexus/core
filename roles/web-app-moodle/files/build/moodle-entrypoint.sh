#!/bin/bash
# Moodle container entrypoint. Bootstrap the persistent code volume
# from ${MOODLE_SOURCE_DIR} on first start, ensure ownership on the
# data dir, then drop privileges (unless launching php-fpm — its
# master process must keep root so the FPM error log can write to
# /proc/self/fd/2; workers fork to ${MOODLE_RUNTIME_USER} per the pool).
# All paths come from env vars exported by the Dockerfile (single
# source of truth: roles/web-app-moodle/vars/main.yml).
set -euo pipefail

: "${MOODLE_CODE_DIR:?required}"
: "${MOODLE_DATA_DIR:?required}"
: "${MOODLE_SOURCE_DIR:?required}"
: "${MOODLE_RUNTIME_USER:?required}"
: "${MOODLE_VERSION_FILE:?required}"

mkdir -p "${MOODLE_DATA_DIR}"
chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_DATA_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

if [ ! -f "${MOODLE_CODE_DIR}/${MOODLE_VERSION_FILE}" ] && [ -d "${MOODLE_SOURCE_DIR}" ]; then
  cp -a "${MOODLE_SOURCE_DIR}/." "${MOODLE_CODE_DIR}/"
fi
chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_CODE_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

if [ "$(id -u)" -eq 0 ] && [ "${1:-}" != "php-fpm" ]; then
  exec gosu "${MOODLE_RUNTIME_USER}" "$@"
fi
exec "$@"
