#!/usr/bin/env sh
# Param $1: "present" installs the theme from stdin and activates it, "absent" removes what an earlier run installed.
# Param $2: plugin name of the theme.
# Param stdin: one "<path> <base64 content>" line per file of the theme, relative to its plugin directory.
# Output: CHANGED when a theme file moved or the activation changed.
set -eu

state="${1:?state is required}"
theme="${2:?theme name is required}"
target="plugins/$theme"
changed=false

cd /var/www/html

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
while read -r path data; do
	[ -n "$path" ] || continue
	mkdir -p "$stage/$(dirname "$path")"
	printf '%s' "$data" | base64 -d >"$stage/$path"
done

is_active() {
	grep -q "^Plugins\[\] = \"$theme\"" config/config.ini.php
}

if [ "$state" = present ]; then
	if [ ! -d "$target" ] || ! diff -r "$stage" "$target" >/dev/null 2>&1; then
		rm -rf "$target"
		mkdir -p "$target"
		cp -R "$stage/." "$target/"
		changed=true
	fi
	if ! is_active; then
		./console plugin:activate "$theme" >/dev/null
		changed=true
	fi
elif [ -f "$target/plugin.json" ]; then
	if is_active; then
		./console plugin:deactivate "$theme" >/dev/null
	fi
	rm -rf "$target"
	changed=true
fi

if [ "$changed" = true ]; then
	./console core:clear-caches >/dev/null
	echo CHANGED
fi
