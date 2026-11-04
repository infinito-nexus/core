#!/usr/bin/env sh
# Param $1: absolute directory of the corporate theme inside the OpenCloud container.
# Param $2: file path below that directory to write; without it the theme directory is removed.
# Param stdin: desired content of that file.
# Output: CHANGED when the file was written or the directory was removed.
# Exit 3: a file is to be written into a directory that does not carry the marker of this role.
set -eu

theme_dir="${1:?theme directory is required}"
marker="$theme_dir/.infinito-design"

if [ "$#" -lt 2 ]; then
	[ -f "$marker" ] || exit 0
	rm -rf "$theme_dir"
	echo CHANGED
	exit 0
fi

if [ -d "$theme_dir" ] && [ ! -f "$marker" ]; then
	echo "$theme_dir exists and was not created by this role" >&2
	exit 3
fi

target="$theme_dir/$2"
desired="$(cat)"

mkdir -p "$(dirname "$target")"
: >"$marker"

if [ -f "$target" ] && [ "$desired" = "$(cat "$target")" ]; then
	exit 0
fi

printf '%s' "$desired" >"$target"
echo CHANGED
