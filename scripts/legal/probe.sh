#!/usr/bin/env bash
set -euo pipefail

# Probe a running instance through its front proxy for the counsel's checks
# the Set-Cookie headers a page sets before consent and the
# reachability of the imprint and privacy pages, from deterministic data.
# Inputs (make vars):
#   target - the instance domain to probe; required

target="${target:-}"
if [ -z "${target}" ]; then
	echo "legal-probe: target=<domain> is required." >&2
	exit 2
fi

echo "# Set-Cookie headers at https://${target}/ (before consent)"
_headers="$(curl -sS -D - -o /dev/null "https://${target}/")"
printf '%s\n' "${_headers}" | grep -i '^set-cookie:' || echo "(no Set-Cookie before consent)"

echo "# Imprint and privacy pages"
for _page in imprint impressum privacy datenschutz; do
	_url="https://${target}/${_page}"
	_code="$(curl -sS -o /dev/null -w '%{http_code}' "${_url}")"
	echo "${_code} ${_url}"
done
