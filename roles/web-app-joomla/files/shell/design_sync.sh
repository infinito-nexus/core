#!/bin/sh
# Param 1: present writes stdin to the file, absent removes a file this script wrote and puts back the one it replaced.
# Param 2: document root of Joomla.
# Param 3: path of the file below the document root.
set -eu
state="$1"
root="$2"
dest="${root}/$3"
marks="${root}/.infinito-design"
key="$(printf '%s' "$3" | tr '/' '_')"
mark="${marks}/${key}.mark"
former="${marks}/${key}.former"

if [ "${state}" = "absent" ]; then
	[ -f "${mark}" ] || exit 0
	rm -f "${dest}" "${mark}"
	if [ -f "${former}" ]; then
		mv "${former}" "${dest}"
	fi
	echo CHANGED
	exit 0
fi

tmp="$(mktemp)"
cat >"${tmp}"
if [ -f "${mark}" ] && [ -f "${dest}" ] && cmp -s "${tmp}" "${dest}"; then
	rm -f "${tmp}"
	exit 0
fi
mkdir -p "${marks}" "$(dirname "${dest}")"
if [ -f "${dest}" ] && [ ! -f "${mark}" ]; then
	mv "${dest}" "${former}"
fi
mv "${tmp}" "${dest}"
chmod 0644 "${dest}"
: >"${mark}"
echo CHANGED
