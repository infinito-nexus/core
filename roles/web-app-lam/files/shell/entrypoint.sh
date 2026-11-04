#!/bin/bash
set -euo pipefail

: "${LAM_LOGIN_SEARCH_SUFFIX:?LAM_LOGIN_SEARCH_SUFFIX must be set}"
: "${LAM_LOGIN_SEARCH_FILTER:?LAM_LOGIN_SEARCH_FILTER must be set}"

LAM_SAMPLE_CONFIG=/var/lib/ldap-account-manager/config/unix.sample.conf

php /usr/local/share/infinito-lam/login_search.php "${LAM_SAMPLE_CONFIG}"

exec /usr/local/bin/start.sh "$@"
