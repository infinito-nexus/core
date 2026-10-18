#!/usr/bin/env sh
# Param $1: absolute path of the file inside the Checkmk container.
# Param $2: directory that is pruned together with its emptied subdirectories once the file is gone; empty prunes nothing.
# Param $3: file that marks the owner of that directory; empty skips the ownership check.
# Param $4: text the marker file carries when this role owns the directory.
# Param stdin: base64 of the desired content of the file; empty removes the file.
# Output: CHANGED when the file was written or removed, FOREIGN when another owner holds the directory.
set -eu

target="${1:?file path is required}"
root="${2:-}"
marker="${3:-}"
mark="${4:-}"
desired="$(cat)"

if [ -n "$marker" ] && [ -e "$marker" ] && ! grep -qF -- "$mark" "$marker"; then
	echo FOREIGN
	exit 0
fi

if [ -z "$desired" ]; then
	[ -e "$target" ] || exit 0
	rm -f "$target"
	if [ -n "$root" ]; then
		dir="$(dirname "$target")"
		while [ "${dir#"$root"}" != "$dir" ] && rmdir "$dir" 2>/dev/null; do
			dir="$(dirname "$dir")"
		done
	fi
	echo CHANGED
	exit 0
fi

if [ -f "$target" ] && [ "$desired" = "$(base64 -w0 "$target")" ]; then
	exit 0
fi

mkdir -p "$(dirname "$target")"
printf '%s' "$desired" | base64 -d >"$target"
echo CHANGED
