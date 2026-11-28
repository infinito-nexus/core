#!/usr/bin/env sh
# Param $1: "present" copies the plugin the image ships into the installation and activates it, "absent" deactivates it.
# Param $2: plugin name.
# Param $3: directory holding the plugin the image ships.
# Output: CHANGED when a plugin file moved or the activation changed.
set -eu

state="${1:?state is required}"
plugin="${2:?plugin name is required}"
source_dir="${3:?source directory is required}"
target="plugins/$plugin"
changed=false

cd /var/www/html

is_active() {
	grep -q "^Plugins\[\] = \"$plugin\"" config/config.ini.php
}

if [ "$state" = present ]; then
	if ! diff -r "$source_dir" "$target" >/dev/null 2>&1; then
		rm -rf "$target"
		cp -R "$source_dir" "$target"
		changed=true
	fi
	if ! is_active; then
		./console plugin:activate "$plugin" >/dev/null
		changed=true
	fi
elif [ "$state" = absent ]; then
	if is_active; then
		./console plugin:deactivate "$plugin" >/dev/null
		changed=true
	fi
else
	echo "unknown state: $state" >&2
	exit 2
fi

if [ "$changed" = true ]; then
	./console core:clear-caches >/dev/null
	echo CHANGED
fi
