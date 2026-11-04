#!/usr/bin/env sh
# Param $1: "present" activates a plugin Matomo ships, "absent" deactivates it.
# Param $2: plugin name.
# Output: CHANGED when the activation changed.
set -eu

state="${1:?state is required}"
plugin="${2:?plugin name is required}"
changed=false

cd /var/www/html

is_active() {
	grep -q "^Plugins\[\] = \"$plugin\"" config/config.ini.php
}

if [ "$state" = present ]; then
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
