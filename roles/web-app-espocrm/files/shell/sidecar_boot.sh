#!/bin/bash
# Usage:
#   sidecar_boot.sh <php-script-name>
#
# Replaces upstream's docker-daemon.sh / docker-websocket.sh, whose readiness gate
# calls `bin/command app-check` -- a command the shipped application does not carry.
# applyConfigEnv is upstream's and must stay: it is the only place the websocket
# service's ESPOCRM_CONFIG_WEB_SOCKET_* variables reach the shared config.php.
set -eu

script="${1:?usage: sidecar_boot.sh <php-script-name>}"

# shellcheck source=/dev/null
source /usr/local/bin/entrypoint-utils.sh
applyConfigEnv

exec /usr/local/bin/php "/var/www/html/${script}"
