#!/bin/bash
set -euo pipefail

: "${LAM_LOGIN_SEARCH_SUFFIX:?LAM_LOGIN_SEARCH_SUFFIX must be set}"
: "${LAM_LOGIN_SEARCH_FILTER:?LAM_LOGIN_SEARCH_FILTER must be set}"

LAM_CONFIG_DIR=/var/lib/ldap-account-manager/config

php /usr/local/share/infinito-lam/login_search.php "${LAM_CONFIG_DIR}/lam.conf" "${LAM_CONFIG_DIR}/unix.sample.conf"

exec /usr/local/bin/start.sh "$@"
