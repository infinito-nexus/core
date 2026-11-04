#!/usr/bin/env sh
# Param $1: module directory, relative to the EspoCRM root, that the payload replaces.
# Param stdin: one "<path> <base64 content>" line per file of the module.
# Output: CHANGED when the module tree moved.
set -eu

module="${1:?module directory is required}"

cd /var/www/html

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
while read -r path data; do
	[ -n "$path" ] || continue
	mkdir -p "$stage/tree/$(dirname "$path")"
	printf '%s' "$data" | base64 -d >"$stage/tree/$path"
done

if [ -d "$module" ] && diff -r "$stage/tree" "$module" >/dev/null 2>&1; then
	exit 0
fi

rm -rf "$module"
mkdir -p "$(dirname "$module")"
cp -R "$stage/tree" "$module"
php command.php clear-cache >/dev/null
echo CHANGED
