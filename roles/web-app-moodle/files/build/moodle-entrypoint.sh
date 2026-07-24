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

MOODLE_BOOTSTRAP_SENTINEL="${MOODLE_CODE_DIR}/.bootstrap.done"
MOODLE_BOOTSTRAP_LOCK="${MOODLE_CODE_DIR}/.bootstrap.lock"

mkdir -p "${MOODLE_DATA_DIR}"
chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_DATA_DIR}" || true

moodle_bootstrap_code_dir() {
  if [ -f "${MOODLE_BOOTSTRAP_SENTINEL}" ]; then
    return 0
  fi
  if [ -d "${MOODLE_SOURCE_DIR}" ]; then
    cp -an "${MOODLE_SOURCE_DIR}/." "${MOODLE_CODE_DIR}/" || true
  fi
  chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_CODE_DIR}" || true
  find "${MOODLE_CODE_DIR}" -type d -exec chmod 0755 {} + || true
  find "${MOODLE_CODE_DIR}" -type f -exec chmod 0644 {} + || true
  touch "${MOODLE_BOOTSTRAP_SENTINEL}"
}

mkdir -p "${MOODLE_CODE_DIR}"
while [ ! -f "${MOODLE_BOOTSTRAP_SENTINEL}" ]; do
  exec 9>>"${MOODLE_BOOTSTRAP_LOCK}"
  if flock -w 30 9; then
    moodle_bootstrap_code_dir
  else
    sleep 5
  fi
  exec 9>&-
done

if [ "$(id -u)" -eq 0 ] && [ "${1:-}" != "php-fpm" ]; then
  exec gosu "${MOODLE_RUNTIME_USER}" "$@"
fi
exec "$@"
