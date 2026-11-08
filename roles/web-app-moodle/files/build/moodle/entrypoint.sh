#!/bin/bash
# Moodle container entrypoint. Bootstrap the persistent code volume
# from ${MOODLE_SOURCE_DIR}, ensure ownership on the
# data dir, then drop privileges (unless launching php-fpm — its
# master process must keep root so the FPM error log can write to
# /proc/self/fd/2; workers fork to ${MOODLE_RUNTIME_USER} per the pool).
# All paths come from env vars exported by the Dockerfile (single
# source of truth: roles/web-app-moodle/vars/main.yml).
#
# The lock sits on the code volume and does not serialize the replicas and
# cron across NFS clients, so the sentinel is re-read after the stage is
# filled: a second swap would wipe the tree the first one installed.
set -euo pipefail

: "${MOODLE_CODE_DIR:?required}"
: "${MOODLE_DATA_DIR:?required}"
: "${MOODLE_LOCAL_CACHE_DIR:?required}"
: "${MOODLE_SOURCE_DIR:?required}"
: "${MOODLE_RUNTIME_USER:?required}"
: "${MOODLE_VERSION_FILE:?required}"
: "${MOODLE_RELEASE:?required}"
: "${MOODLE_RELEASE_LIB:?required}"
: "${MOODLE_TRANSIT_DIR:?required}"
: "${MOODLE_UPGRADE_PATH:?required}"
: "${MOODLE_CLI_RELPATH:?required}"
: "${MOODLE_BOOTSTRAP_STAGE:?required}"
: "${MOODLE_BOOTSTRAP_SENTINEL:?required}"

# shellcheck source=roles/web-app-moodle/files/build/moodle/release.sh
. "${MOODLE_RELEASE_LIB}"

MOODLE_BOOTSTRAP_LOCK="${MOODLE_CODE_DIR}/.bootstrap.lock"
MOODLE_UPGRADE_CLI="${MOODLE_CODE_DIR}/${MOODLE_CLI_RELPATH}/upgrade.php"

mkdir -p "${MOODLE_DATA_DIR}"
chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_DATA_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

mkdir -p "${MOODLE_LOCAL_CACHE_DIR}"
if [ "$(id -u)" -eq 0 ]; then
  chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_LOCAL_CACHE_DIR}"
fi

moodle_code_dir_is_current() {
  [ "$(cat "${MOODLE_BOOTSTRAP_SENTINEL}" 2>/dev/null)" = "${MOODLE_RELEASE}" ]
}

moodle_as_runtime_user() {
  if [ "$(id -u)" -eq 0 ]; then
    gosu "${MOODLE_RUNTIME_USER}" "$@"
  else
    "$@"
  fi
}

moodle_recorded_release() {
  local recorded file
  recorded="$(cat "${MOODLE_BOOTSTRAP_SENTINEL}" 2>/dev/null)" || recorded=""
  if [ -n "${recorded}" ]; then
    moodle_normalize_release "${recorded}"
    return
  fi
  for file in "${MOODLE_CODE_DIR}/${MOODLE_VERSION_FILE}" "${MOODLE_CODE_DIR}/version.php"; do
    [ -f "${file}" ] || continue
    if ! moodle_release_of "${file}"; then
      echo "${file} declares no \$release, so the Moodle release in the code volume is unknown; refusing to replace it." >&2
      exit 1
    fi
    return 0
  done
}

moodle_report_legacy_layout() {
  [ -e "${MOODLE_BOOTSTRAP_SENTINEL}" ] && return 0
  grep -q '/bitnami/' "${MOODLE_CODE_DIR}/config.php" 2>/dev/null || return 0
  echo "The code volume holds Moodle $1 in the Bitnami layout; migrating it: ${MOODLE_CODE_DIR} gets the tree of this image, ${MOODLE_DATA_DIR} keeps the data and belongs to ${MOODLE_RUNTIME_USER}." >&2
}

moodle_fill_stage_from_source() {
  cp -a "${MOODLE_SOURCE_DIR}/." "${MOODLE_BOOTSTRAP_STAGE}/"
}

moodle_fill_stage_from_transit() {
  tar -xzf "${MOODLE_TRANSIT_DIR}/$1.tar.gz" --strip-components=1 -C "${MOODLE_BOOTSTRAP_STAGE}"
}

moodle_swap_code_dir() {
  rm -rf "${MOODLE_BOOTSTRAP_STAGE}"
  mkdir "${MOODLE_BOOTSTRAP_STAGE}"
  "$@"
  if moodle_code_dir_is_current; then
    rm -rf "${MOODLE_BOOTSTRAP_STAGE}"
    return 0
  fi
  find "${MOODLE_CODE_DIR}" -mindepth 1 -maxdepth 1 ! -name "${MOODLE_BOOTSTRAP_LOCK##*/}" ! -name "${MOODLE_BOOTSTRAP_STAGE##*/}" ! -name "${MOODLE_BOOTSTRAP_SENTINEL##*/}" -exec rm -rf {} +
  find "${MOODLE_BOOTSTRAP_STAGE}" -mindepth 1 -maxdepth 1 -exec mv -t "${MOODLE_CODE_DIR}" {} +
  rmdir "${MOODLE_BOOTSTRAP_STAGE}"
  chown -R "${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER}" "${MOODLE_CODE_DIR}" || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  find "${MOODLE_CODE_DIR}" -type d -exec chmod 0755 {} + || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  find "${MOODLE_CODE_DIR}" -type f -exec chmod 0644 {} + || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
}

moodle_require_installed_site() {
  local probe rc=0
  probe="$(moodle_as_runtime_user php "${MOODLE_UPGRADE_CLI}" --is-pending 2>&1)" || rc=$?
  case "${rc}" in
    0 | 2) return 0 ;;
  esac
  echo "The code volume held Moodle $1, but Moodle ${MOODLE_RELEASE} reads no installed site from its database (upgrade.php --is-pending exited ${rc}: ${probe}); refusing to start, because the deploy would install a new site over the data of the old one." >&2
  exit 1
}

moodle_pass_through() {
  echo "Moodle ${MOODLE_RELEASE} upgrades no site older than its minimum source, and the code volume holds $1; passing through $2 first." >&2
  moodle_swap_code_dir moodle_fill_stage_from_transit "$2"
  moodle_refresh_config
  moodle_as_runtime_user php "${MOODLE_UPGRADE_CLI}" --non-interactive
  printf '%s' "$2" > "${MOODLE_BOOTSTRAP_SENTINEL}"
  echo "Moodle database upgraded from $1 to $2." >&2
}

moodle_bootstrap_code_dir() {
  local pinned recorded next
  if moodle_code_dir_is_current; then
    return 0
  fi
  pinned="$(moodle_normalize_release "${MOODLE_RELEASE}")"
  recorded="$(moodle_recorded_release)"
  if [ -z "${recorded}" ]; then
    moodle_swap_code_dir moodle_fill_stage_from_source
    printf '%s' "${MOODLE_RELEASE}" > "${MOODLE_BOOTSTRAP_SENTINEL}"
    return 0
  fi
  if ! moodle_release_at_least "${pinned}" "${recorded}"; then
    echo "The code volume holds Moodle ${recorded}, this image ships the older ${MOODLE_RELEASE}; refusing to replace it." >&2
    exit 1
  fi
  moodle_report_legacy_layout "${recorded}"
  [ -s "${MOODLE_BOOTSTRAP_SENTINEL}" ] || printf '%s' "${recorded}" > "${MOODLE_BOOTSTRAP_SENTINEL}"
  next="${pinned}"
  if [ "${recorded}" != "${pinned}" ] && ! next="$(moodle_next_release "${recorded}" "${MOODLE_UPGRADE_PATH}")"; then
    echo "The code volume holds Moodle ${recorded}, older than every release this image upgrades from ($(tr '\n' ';' < "${MOODLE_UPGRADE_PATH}") as release and oldest source); upgrade it to one of those sources first." >&2
    exit 1
  fi
  if [ "${next}" != "${pinned}" ]; then
    moodle_pass_through "${recorded}" "${next}"
    return 0
  fi
  moodle_swap_code_dir moodle_fill_stage_from_source
  moodle_refresh_config
  moodle_require_installed_site "${recorded}"
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
