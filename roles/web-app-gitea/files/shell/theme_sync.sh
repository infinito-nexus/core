#!/usr/bin/env sh
# Param $1: absolute path of the theme file inside the Gitea container.
# Param stdin: desired content of that file; empty removes the file.
# Output: CHANGED when the file was written or removed.
set -eu

target="${1:?theme file path is required}"
desired="$(cat)"

if [ -z "$desired" ]; then
	[ -e "$target" ] || exit 0
	rm -f "$target"
	echo CHANGED
	exit 0
fi

if [ -f "$target" ] && [ "$desired" = "$(cat "$target")" ]; then
	exit 0
fi

mkdir -p "$(dirname "$target")"
printf '%s\n' "$desired" >"$target"
echo CHANGED
