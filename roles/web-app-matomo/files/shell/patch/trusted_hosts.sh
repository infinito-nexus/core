#!/bin/sh
# Env: CFG     Path to config.ini.php on the matomo_data volume (host bind path).
# Env: DOMAIN  Public canonical domain to land in the first trusted_hosts slot.
# Env: SIBLINGS Space-separated network siblings of DOMAIN (each added as a trusted host).
# Env: SERVICE Stack-internal service name (added as a trusted host).
# Env: LOCAL   host:port the role uses for in-host probes (added as a trusted host).
# Output: "PATCHED" when the content of CFG changed, nothing when it already matched.
set -eu

before="$(cksum <"$CFG")"

ensure_host() {
  host="$1"
  if ! grep -qE "^trusted_hosts\[\][[:space:]]*= \"${host}\"$" "$CFG"; then
    awk -v host="$host" '
      BEGIN{added=0}
      /^\[General\]$/ { print; next }
      /^trusted_hosts\[\][[:space:]]*=/ && !added {
        print
        print "trusted_hosts[] = \""host"\""
        added=1
        next
      }
      { print }
      END{
        if (!added) {
          print "[General]"
          print "trusted_hosts[] = \""host"\""
        }
      }
    ' "$CFG" > "$CFG.tmp" && mv "$CFG.tmp" "$CFG"
  fi
}

sed -i "0,/^trusted_hosts\[\].*/s//trusted_hosts[] = \"${DOMAIN}\"/" "$CFG"

for sibling in ${SIBLINGS}; do
  ensure_host "$sibling"
done
ensure_host "$SERVICE"
ensure_host "$LOCAL"

if ! grep -qE "^enable_framed_pages[[:space:]]*=" "$CFG"; then
  awk '
    /^\[General\]$/ { print; print "enable_framed_pages = 1"; next }
    { print }
  ' "$CFG" > "$CFG.tmp" && mv "$CFG.tmp" "$CFG"
fi

[ "$(cksum <"$CFG")" = "$before" ] || echo PATCHED
