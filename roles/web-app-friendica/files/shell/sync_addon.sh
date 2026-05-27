#!/usr/bin/env bash
#
# Sync one Friendica addon to the requested enabled-state.
#
# `bin/console addon enable` only fires the addon's `_install` hooks on
# the disabled→enabled transition. An already-enabled-but-broken state
# (the addon is listed as enabled but its hooks are missing from the
# `hook` DB table) silently rejects every authenticate hook at runtime,
# so we force-cycle disable+enable for the enabled case. The verify
# step at the bottom catches that failure mode by checking
# `addon list enabled`.
#
# Usage:
#   sync_addon.sh CMD ADDON DESIRED_STATE
#     CMD            full bin/console invocation prefix as a single arg
#                    (typical: 'docker compose exec -T --user www-data
#                    --workdir /var/www/html friendica /var/www/html/bin/console')
#     ADDON          addon name (e.g. ldapauth)
#     DESIRED_STATE  'true' or 'false'
set -euo pipefail

CMD="$1"
ADDON="$2"
DESIRED="$3"

if [[ "$DESIRED" == "true" ]]; then
    $CMD addon disable "$ADDON" 2>&1 || true
    $CMD addon enable  "$ADDON" 2>&1 || true
else
    $CMD addon disable "$ADDON" 2>&1 || true
fi

if $CMD addon list enabled | grep -qE "^\| +${ADDON} +\|$"; then
    is_enabled=1
else
    is_enabled=0
fi

want=0
[[ "$DESIRED" == "true" ]] && want=1
test "$is_enabled" = "$want"
