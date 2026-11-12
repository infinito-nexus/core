#!/usr/bin/env bash
# Usage: refresh_extensions.sh HTML_DIR VOLUME_DIR MARKER
#   HTML_DIR    MediaWiki installation directory of the image
#   VOLUME_DIR  mount point of the extensions volume, outside HTML_DIR so the image's HTML_DIR/extensions stays visible
#   MARKER      file name inside VOLUME_DIR that records the MediaWiki version of its content
#
# Env: MEDIAWIKI_VERSION, set by the official MediaWiki image.
# Prints one status line:
#   CURRENT:<version>             the volume records the image's version
#   ADOPTED:<version>             no record, but the bundled extensions match the image
#   REFRESHED:<recorded>-><version>  the volume content was replaced by the image's extensions
# Exits 3 after printing REFUSED when the volume records a newer version than the image.
set -euo pipefail

HTML_DIR="$1"
VOLUME_DIR="$2"
MARKER="${VOLUME_DIR}/$3"
VERSION="${MEDIAWIKI_VERSION:?MEDIAWIKI_VERSION must be set by the MediaWiki image}"
BUNDLED="${HTML_DIR}/extensions"

matches_image() {
	local manifest found=0
	for manifest in "${BUNDLED}"/*/extension.json; do
		[[ -f "${manifest}" ]] || continue
		found=1
		cmp -s "${manifest}" "${VOLUME_DIR}/${manifest#"${BUNDLED}/"}" || return 1
	done
	[[ "${found}" -eq 1 ]]
}

recorded=""
if [[ -f "${MARKER}" ]]; then
	recorded="$(<"${MARKER}")"
fi

if [[ "${recorded}" == "${VERSION}" ]]; then
	echo "CURRENT:${VERSION}"
	exit 0
fi

if [[ -n "${recorded}" ]] && [[ "$(printf '%s\n%s\n' "${recorded}" "${VERSION}" | sort -V | tail -n 1)" == "${recorded}" ]]; then
	echo "REFUSED: the extensions volume holds MediaWiki ${recorded}, newer than the image's ${VERSION}"
	exit 3
fi

if [[ -z "${recorded}" ]] && matches_image; then
	printf '%s\n' "${VERSION}" >"${MARKER}"
	echo "ADOPTED:${VERSION}"
	exit 0
fi

find "${VOLUME_DIR}" -mindepth 1 -delete
cp -a "${BUNDLED}/." "${VOLUME_DIR}/"
printf '%s\n' "${VERSION}" >"${MARKER}"
echo "REFRESHED:${recorded:-none}->${VERSION}"
