#!/bin/sh
# Param: $1              config.ini.php to rewrite in place.
# Param: PATCH_HOST      database host, escaped for the / delimiter.
# Param: PATCH_NAME      database name, escaped for the / delimiter.
# Param: PATCH_USERNAME  database user, escaped for the / delimiter.
# Param: PATCH_PASSWORD  database password, escaped for the / delimiter.
# Output: "PATCHED" when the content of $1 changed, nothing when it already matched.
set -eu

config="$1"

rewrite() {
	sed "$@" \
		-e "s/^host *=.*/host = ${PATCH_HOST}/" \
		-e "s/^dbname *=.*/dbname = ${PATCH_NAME}/" \
		-e "s/^username *=.*/username = ${PATCH_USERNAME}/" \
		-e "s/^password *=.*/password = ${PATCH_PASSWORD}/" \
		"${config}"
}

[ "$(rewrite | cksum)" = "$(cksum <"${config}")" ] && exit 0
rewrite -i
echo PATCHED
