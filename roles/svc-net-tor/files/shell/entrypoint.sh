#!/bin/sh
set -eu

if [ "${TOR_FLAVOR}" = "chutney" ]; then
    "${TOR_CHUTNEY_SCRIPT_PATH}" run /opt/chutney "${TOR_CHUTNEY_ADDRESS}" /run/tor/chutney-net.conf
fi

exec tor "$@"
