#!/usr/bin/env bash
# List the collected rescue tree and where to download it.
#
# Arguments:
#   $1 DIR    rescue directory to index; a missing directory is not an error
#   $2 LIMIT  max paths to list, default 400
#
# Exit status: always 0.
set -euo pipefail
trap 'exit 0' EXIT

DIR="${1:?usage: rescue_index.sh DIR [LIMIT]}"
LIMIT="${2:-400}"

[ -d "${DIR}" ] || exit 0

if LISTING="$(find "${DIR}" -mindepth 1 -printf '%y %10s %P\n' 2>/dev/null |
	tr '/' '\001' | LC_ALL=C sort -k3 | tr '\001' '/')"; then
	WALKED=true
else
	WALKED=false
fi
if ! SIZE="$(du -sh "${DIR}" 2>/dev/null | cut -f1)"; then
	[ -n "${SIZE}" ] || SIZE="unknown size"
fi

ENTRIES=0
[ -z "${LISTING}" ] || ENTRIES="$(printf '%s\n' "${LISTING}" | wc -l)"
FILES="$(printf '%s\n' "${LISTING}" | awk '$1 == "f"' | wc -l)"

echo "🩺 Rescue diagnostics: ${FILES} file(s), ${SIZE}, under ${DIR}"
echo "   Download them from the 'rescue-diagnostics-*' artifact on this run's summary page."
echo "   The tree below is the artifact root; file contents are NOT printed here."

[ "${WALKED}" = true ] ||
	echo "   The walk over ${DIR} was cut short; what follows is only what could be read."

[ -z "${LISTING}" ] || printf '%s\n' "${LISTING}" | sed -n "1,${LIMIT}p" | awk '
{
	type = $1
	size = $2
	path = $0
	sub(/^[^ ]+[ ]+[^ ]+[ ]+/, "", path)
	depth = split(path, part, "/")
	indent = "   "
	for (i = 1; i < depth; i++) {
		indent = indent "  "
	}
	name = part[depth]
	if (type == "d") {
		printf "%s📁 %s/\n", indent, name
	} else {
		glyph = "📄"
		if (name ~ /\.json$/) {
			glyph = "🧾"
		} else if (name ~ /\.(log|journal|txt)$/ && name ~ /journal|log/) {
			glyph = "📜"
		}
		printf "%s%s %s  (%s)\n", indent, glyph, name, size
	}
}'

if [ "${ENTRIES}" -gt "${LIMIT}" ]; then
	echo "   ... $((ENTRIES - LIMIT)) further path(s) not listed; all of them are in the artifact."
fi
