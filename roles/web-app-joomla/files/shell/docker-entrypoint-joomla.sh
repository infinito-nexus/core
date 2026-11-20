#!/bin/bash
webroot="${JOOMLA_WEBROOT:?JOOMLA_WEBROOT must be set}"
stock="${JOOMLA_STOCK_ENTRYPOINT:?JOOMLA_STOCK_ENTRYPOINT must be set}"
ready="${JOOMLA_INIT_READY_FILE:?JOOMLA_INIT_READY_FILE must be set}"
stale_after="${JOOMLA_INIT_LOCK_STALE_SECONDS:?JOOMLA_INIT_LOCK_STALE_SECONDS must be set}"
lock="${webroot}/.infinito-init.lock"
owner="${lock}/owner"
marker="${webroot}/.joomla-initializing"
pending="${webroot}/.infinito-init.cleanup"
config="${webroot}/configuration.php"
token="${HOSTNAME}.$$.$(date +%s%N)"
beat=$((stale_after / 4 + 1))
heartbeat_pid=""

trap 'exit 143' TERM
trap 'exit 130' INT

log_error() {
  printf '[ERROR] %s\n' "$1" >&2
}

initialized() {
  [ -e "${ready}" ] || { [ -s "${config}" ] && [ ! -e "${marker}" ]; }
}

stale() {
  local stamp
  stamp="$(stat -c %Y "$1/owner" 2>/dev/null)" ||
    stamp="$(stat -c %Y "$1" 2>/dev/null)" ||
    return 1
  [ $(($(date +%s) - stamp)) -gt "${stale_after}" ]
}

take_over_stale() {
  local moved="${lock}.stale.${token}"
  stale "${lock}" || return 1
  mv -T "${lock}" "${moved}" 2>/dev/null || return 1
  if stale "${moved}"; then
    rm -rf "${moved}"
    return 0
  fi
  mv -T "${moved}" "${lock}"
  return 1
}

heartbeat() {
  while sleep "${beat}"; do
    touch "${owner}"
  done
}

release() {
  if [ -n "${heartbeat_pid}" ]; then
    kill "${heartbeat_pid}" 2>/dev/null
  fi
  heartbeat_pid=""
  if [ "$(cat "${owner}" 2>/dev/null)" = "${token}" ]; then
    rm -rf "${lock}"
  fi
}

run_setup() {
  local log
  log="$(mktemp)"
  # Exception: since docker-joomla 327d05a9f1 the stock entrypoint skips its
  # setup for -v/-V/-h/-t/-T; `apache2 -l` still runs it and then returns.
  { "${stock}" apache2 -l 2>&1 | tee "${log}"; } &
  wait "$!"
  # Exception: Joomla's installer deletes installation/ while it still holds
  # installation/joomla.php open; NFS keeps that file as a .nfs silly rename,
  # so a complete install reports failure and the stock entrypoint keeps its
  # marker.
  if [ -s "${config}" ] && [ -d "${marker}" ] &&
    grep -q 'Unable to delete installation folder' "${log}" &&
    ! grep -qE 'Failed to (correct ownership|restore configuration)|Refusing to change permissions' "${log}"; then
    touch "${pending}"
  fi
  rm -f "${log}"
}

finish_cleanup() {
  rm -rf "${webroot}/installation" || return 1
  rm -f "${webroot}/joomla.xml" || return 1
  if [ ! -e "${webroot}/robots.txt" ] && [ -e "${webroot}/robots.txt.dist" ]; then
    mv "${webroot}/robots.txt.dist" "${webroot}/robots.txt" || return 1
  fi
  rmdir "${marker}" || return 1
  rm -f "${pending}"
}

recover() {
  if [ ! -e "${marker}" ]; then
    run_setup
  fi
  if [ -e "${marker}" ] && [ -e "${pending}" ] && ! finish_cleanup; then
    log_error "Finishing Joomla's installer cleanup in ${webroot} failed; ${pending} stays, so the next start retries it."
    return 1
  fi
  if initialized; then
    touch "${ready}"
    return 0
  fi
  if [ -e "${marker}" ]; then
    log_error "${marker} remains from an unfinished Joomla setup. If that setup stopped at 'Unable to delete installation folder!', run 'touch ${pending}' and restart; otherwise restore the site and database, then remove ${marker}."
  fi
  return 1
}

lead() {
  local status
  printf '%s\n' "${token}" > "${owner}"
  trap release EXIT
  heartbeat &
  heartbeat_pid=$!
  recover
  status=$?
  release
  trap - EXIT
  return "${status}"
}

until initialized; do
  if mkdir "${lock}" 2>/dev/null; then
    lead || exit 1
  elif ! take_over_stale; then
    sleep 2
  fi
done

exec "${stock}" "$@"
