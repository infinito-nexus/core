#!/bin/bash
# Install and activate one WordPress plugin through WP-CLI.
#
# WP-CLI can exit 255 after an install that finished, because WordPress' fatal
# handler requires the .maintenance file the install has just removed. The
# install's exit code is therefore never the verdict: the retry stops on
# "Success:", and `wp plugin is-installed` afterwards decides whether the
# plugin is really there.
#
# Every other probe does count. A probe that answers with an unexpected code
# aborts, because `set -e` is suspended inside an `if` condition and a probe
# folded into one would turn a broken container into "nothing to do".
#
# Environment:
#   WP_PLUGIN          plugin slug
#   WP_SOURCE          install source: the slug, or a release URL when pinned
#   WP_PINNED_VERSION  version the pin demands, without a leading v; empty when unpinned
#   WP_REQUIRED        "true" when a plugin that stays missing must fail the deploy
#   WP_NETWORK         "true" to activate across every site of a multisite network
#   WP_CONTAINER       container to exec into
#   WP_USER            user inside the container
#   WP_PATH            WordPress document root inside the container
#
# Prints "infinito-changed" when it installed, updated or activated something.
#
# Exit codes:
#   0   installed and activated, or optional and still missing
#   64  a required environment variable is unset
#   65  a required plugin is still missing after every attempt
#   66  `wp plugin is-installed` answered with an unexpected exit code
#   67  `wp plugin get` could not read the installed version of a pinned plugin
set -euo pipefail

ATTEMPTS=3
RETRY_DELAY=10

WP_PINNED_VERSION="${WP_PINNED_VERSION:-}"
WP_REQUIRED="${WP_REQUIRED:-false}"
WP_NETWORK="${WP_NETWORK:-false}"
CHANGED=0
NEEDS_INSTALL=0

require() {
  if [ -z "${2:-}" ]; then
    echo "install-plugin: $1 is required" >&2
    exit 64
  fi
}

require WP_PLUGIN "${WP_PLUGIN:-}"
require WP_SOURCE "${WP_SOURCE:-}"
require WP_CONTAINER "${WP_CONTAINER:-}"
require WP_USER "${WP_USER:-}"
require WP_PATH "${WP_PATH:-}"

wp_cli() {
  container exec -u "$WP_USER" "$WP_CONTAINER" wp "$@" --path="$WP_PATH"
}

is_installed() {
  local rc=0
  wp_cli plugin is-installed "$WP_PLUGIN" >/dev/null 2>&1 || rc=$?
  if [ "$rc" -gt 1 ]; then
    echo "install-plugin: 'wp plugin is-installed $WP_PLUGIN' exited $rc" >&2
    exit 66
  fi
  return "$rc"
}

decide_install() {
  if ! is_installed; then
    NEEDS_INSTALL=1
    return 0
  fi
  [ -n "$WP_PINNED_VERSION" ] || return 0
  local rc=0 out
  out=$(wp_cli plugin get "$WP_PLUGIN" --field=version) || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "install-plugin: 'wp plugin get $WP_PLUGIN' exited $rc" >&2
    exit 67
  fi
  if [ "$(printf '%s' "$out" | tr -d '[:space:]')" != "$WP_PINNED_VERSION" ]; then
    NEEDS_INSTALL=1
  fi
}

install_plugin() {
  local attempt=1 rc out
  while :; do
    rc=0
    if [ -n "$WP_PINNED_VERSION" ]; then
      out=$(wp_cli plugin install "$WP_SOURCE" --force 2>&1) || rc=$?
    else
      out=$(wp_cli plugin install "$WP_SOURCE" 2>&1) || rc=$?
    fi
    printf '%s\n' "$out"
    if [ "$rc" -eq 0 ] || printf '%s' "$out" | grep -q 'Success:'; then
      break
    fi
    if [ "$attempt" -ge "$ATTEMPTS" ]; then
      break
    fi
    attempt=$((attempt + 1))
    sleep "$RETRY_DELAY"
  done
  if printf '%s' "$out" | grep -qE 'Plugin (installed|updated) successfully'; then
    CHANGED=1
  fi
}

activate() {
  local rc=0 out
  if [ "$WP_NETWORK" = "true" ]; then
    out=$(wp_cli plugin activate "$WP_PLUGIN" --network 2>&1) || rc=$?
  else
    out=$(wp_cli plugin activate "$WP_PLUGIN" 2>&1) || rc=$?
  fi
  printf '%s\n' "$out"
  [ "$rc" -eq 0 ] || return "$rc"
  if ! printf '%s' "$out" | tr '[:upper:]' '[:lower:]' | grep -q already; then
    CHANGED=1
  fi
}

decide_install

installed=1
if [ "$NEEDS_INSTALL" -eq 1 ]; then
  install_plugin
  installed=0
  is_installed && installed=1
fi

if [ "$installed" -eq 0 ]; then
  if [ "$WP_REQUIRED" = "true" ]; then
    echo "install-plugin: required plugin '$WP_PLUGIN' did not install from $WP_SOURCE" >&2
    exit 65
  fi
  echo "::warning title=addon install failed::optional plugin '$WP_PLUGIN' did not install; activation skipped"
  exit 0
fi

activate

[ "$CHANGED" -eq 0 ] || echo infinito-changed
