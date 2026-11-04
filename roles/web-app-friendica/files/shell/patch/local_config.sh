#!/bin/sh
# Param: $1              local.config.php to rewrite in place.
# Param: PATCH_HOSTNAME  database host:port, escaped for the / delimiter.
# Param: PATCH_DATABASE  database name, escaped for the / delimiter.
# Param: PATCH_USERNAME  database user, escaped for the / delimiter.
# Param: PATCH_PASSWORD  database password, escaped for the / delimiter.
# Param: PATCH_URL       system.url, escaped for the # delimiter.
# Output: "PATCHED" when the content of $1 changed, nothing when it already matched.
set -eu

config="$1"
script="$(mktemp)"
trap 'rm -f "${script}"' EXIT

printf '%s\n' \
	"s/('hostname'\s*=>\s*')[^']*(',)/\1${PATCH_HOSTNAME}\2/" \
	"s/('database'\s*=>\s*')[^']*(',)/\1${PATCH_DATABASE}\2/" \
	"s/('username'\s*=>\s*')[^']*(',)/\1${PATCH_USERNAME}\2/" \
	"s/('password'\s*=>\s*')[^']*(',)/\1${PATCH_PASSWORD}\2/" \
	"s#('url'\s*=>\s*')[^']*(',)#\1${PATCH_URL}\2#" \
	>"${script}"

rewrite() {
	sed -E "$@" -f "${script}" "${config}"
}

[ "$(rewrite | cksum)" = "$(cksum <"${config}")" ] && exit 0
rewrite -i
echo PATCHED
