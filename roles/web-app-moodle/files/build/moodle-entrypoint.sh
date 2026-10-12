#!/bin/bash
# Moodle container entrypoint. Bootstrap the persistent code volume
# from ${MOODLE_SOURCE_DIR}, ensure ownership on the
# data dir, then drop privileges (unless launching php-fpm — its
# master process must keep root so the FPM error log can write to
# /proc/self/fd/2; workers fork to ${MOODLE_RUNTIME_USER} per the pool).
# All paths come from env vars exported by the Dockerfile (single
# source of truth: roles/web-app-moodle/vars/main.yml).
set -euo pipefail

: "${MOODLE_CODE_DIR:?required}"
: "${MOODLE_DATA_DIR:?required}"
: "${MOODLE_LOCAL_CACHE_DIR:?required}"
: "${MOODLE_SOURCE_DIR:?required}"
: "${MOODLE_RUNTIME_USER:?required}"
: "${MOODLE_VERSION_FILE:?required}"
: "${MOODLE_RELEASE:?required}"

MOODLE_BOOTSTRAP_SENTINEL="${MOODLE_CODE_DIR}/.bootstrap.done"
MOODLE_BOOTSTRAP_LOCK="${MOODLE_CODE_DIR}/.bootstrap.lock"
MOODLE_BOOTSTRAP_STAGE="${MOODLE_CODE_DIR}/.bootstrap.stage"

mkdir -p "${MOODLE_DATA_DIR}"
chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_DATA_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

mkdir -p "${MOODLE_LOCAL_CACHE_DIR}"
if [ "$(id -u)" -eq 0 ]; then
  chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_LOCAL_CACHE_DIR}"
fi

moodle_code_dir_is_current() {
  [ "$(cat "${MOODLE_BOOTSTRAP_SENTINEL}" 2>/dev/null)" = "${MOODLE_RELEASE}" ]
}

moodle_code_dir_is_newer() {
  local recorded newest
  recorded="$(cat "${MOODLE_BOOTSTRAP_SENTINEL}" 2>/dev/null)" || return 1
  [ -n "${recorded}" ] || return 1
  newest="$(printf '%s\n' "${recorded}" "${MOODLE_RELEASE}" | sort -V | tail -n 1)"
  [ "${newest}" = "${recorded}" ] && [ "${recorded}" != "${MOODLE_RELEASE}" ]
}

moodle_bootstrap_code_dir() {
  if moodle_code_dir_is_current; then
    return 0
  fi
  if moodle_code_dir_is_newer; then
    echo "The code volume holds Moodle $(cat "${MOODLE_BOOTSTRAP_SENTINEL}"), this image ships the older ${MOODLE_RELEASE}; refusing to replace it." >&2
    exit 1
  fi
  rm -rf "${MOODLE_BOOTSTRAP_STAGE}"
  mkdir "${MOODLE_BOOTSTRAP_STAGE}"
  cp -a "${MOODLE_SOURCE_DIR}/." "${MOODLE_BOOTSTRAP_STAGE}/"
  find "${MOODLE_CODE_DIR}" -mindepth 1 -maxdepth 1 ! -name "${MOODLE_BOOTSTRAP_LOCK##*/}" ! -name "${MOODLE_BOOTSTRAP_STAGE##*/}" -exec rm -rf {} +
  find "${MOODLE_BOOTSTRAP_STAGE}" -mindepth 1 -maxdepth 1 -exec mv -t "${MOODLE_CODE_DIR}" {} +
  rmdir "${MOODLE_BOOTSTRAP_STAGE}"
  chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_CODE_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  find "${MOODLE_CODE_DIR}" -type d -exec chmod 0755 {} + || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  find "${MOODLE_CODE_DIR}" -type f -exec chmod 0644 {} + || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  printf '%s' "${MOODLE_RELEASE}" > "${MOODLE_BOOTSTRAP_SENTINEL}"
}

moodle_refresh_config() {
	if [ ! -f "${MOODLE_SOURCE_DIR}/config.php" ]; then
		return 0
	fi
	cp -f "${MOODLE_SOURCE_DIR}/config.php" "${MOODLE_CODE_DIR}/config.php"
	if [ "$(id -u)" -eq 0 ]; then
		chown "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_CODE_DIR}/config.php"
		chmod 0640 "${MOODLE_CODE_DIR}/config.php"
	fi
}

mkdir -p "${MOODLE_CODE_DIR}"
until moodle_code_dir_is_current; do
  exec 9>>"${MOODLE_BOOTSTRAP_LOCK}"
  if flock -w 30 9; then
    moodle_bootstrap_code_dir
  else
    sleep 5
  fi
  exec 9>&-
done

moodle_refresh_config

if [ "$(id -u)" -eq 0 ] && [ "${1:-}" != "php-fpm" ]; then
  exec gosu "${MOODLE_RUNTIME_USER}" "$@"
fi
exec "$@"
