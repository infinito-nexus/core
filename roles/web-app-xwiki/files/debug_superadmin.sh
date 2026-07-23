#!/usr/bin/env bash
#
# Debug helper: dump the result of a previous /xwiki/bin/get URL probe
# alongside the superadmin password-hash both sides have on disk, so a
# failed superadmin authentication during the extensions phase produces
# enough context to find the mismatch (typo in inventory, stale
# xwiki.cfg, etc.) — the `register`-ed result of the calling task is
# passed in via positional args.
#
# Usage:
#   debug_superadmin.sh \
#       STATUS REDIRECTED URL WWW_AUTHENTICATE CONTENT_TYPE CONTENT_HEAD \
#       XWIKI_CONTAINER ANSIBLE_PASSWORD
set -euo pipefail

STATUS="$1"
REDIRECTED="$2"
URL="$3"
WWW_AUTHENTICATE="$4"
CONTENT_TYPE="$5"
CONTENT_HEAD="$6"
XWIKI_CONTAINER="$7"
ANSIBLE_PASSWORD="$8"

echo "=== superadmin check ==="
echo "status=$STATUS"
echo "redirected=$REDIRECTED"
echo "url=$URL"
echo "www_authenticate=$WWW_AUTHENTICATE"
echo "content_type=$CONTENT_TYPE"
echo "content=$CONTENT_HEAD"

echo "=== password hash compare ==="
echo -n "container_hash="
# shellcheck disable=SC2016
# Single-quoted on purpose: the inner expansions ($cfg, $1, …) are
# evaluated by the *container's* shell, not the host shell.
container exec "$XWIKI_CONTAINER" sh -lc '
    cfg="/usr/local/tomcat/webapps/ROOT/WEB-INF/xwiki.cfg"
    if [ ! -f "$cfg" ]; then
        echo "<missing-xwiki.cfg>"
        exit 0
    fi
    grep -E "^xwiki\.superadminpassword=" "$cfg" \
        | sed "s/^xwiki\.superadminpassword=//" \
        | sha256sum | awk "{print \$1}"
' || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

echo -n "ansible_hash="
printf '%s' "$ANSIBLE_PASSWORD" | sha256sum | awk '{print $1}'
