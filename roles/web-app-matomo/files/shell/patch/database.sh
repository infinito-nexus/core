#!/bin/sh
# Param: $1              config.ini.php to rewrite in place.
# Param: PATCH_HOST      database host, escaped for the / delimiter.
# Param: PATCH_NAME      database name, escaped for the / delimiter.
# Param: PATCH_USERNAME  database user, escaped for the / delimiter.
# Param: stdin           first line: database password, escaped for the / delimiter.
# Output: "PATCHED" when the content of $1 changed, nothing when it already matched.
set -eu

config="$1"
IFS= read -r PATCH_PASSWORD || : # nocheck: shell-or-true -- read returns 1 on a last line without a newline; the next line rejects an empty value
: "${PATCH_PASSWORD:?the password arrives on stdin}"

rewrite() {
	printf '%s\n' \
		"s/^host *=.*/host = ${PATCH_HOST}/" \
		"s/^dbname *=.*/dbname = ${PATCH_NAME}/" \
		"s/^username *=.*/username = ${PATCH_USERNAME}/" \
		"s/^password *=.*/password = ${PATCH_PASSWORD}/" |
		sed "$@" -f /dev/stdin "${config}"
}

[ "$(rewrite | cksum)" = "$(cksum <"${config}")" ] && exit 0
rewrite -i
echo PATCHED
