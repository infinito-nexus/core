#!/bin/sh
# Param $1: object icon name, used as object and as object id
# Param $2: "present" imports the image, "absent" imports it only over an icon this script marked
# Param $3: path of the backend console
# Param $4: directory that keeps one marker per imported icon
# Param stdin: the PNG image, base64 encoded
# Output: CONVERGED when the icon was imported, KEPT when nothing was written
set -eu

icon="$1"
state="$2"
console="$3"
marker_dir="$4"
marker="${marker_dir}/${icon}.sha256"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

base64 -d >"${work}/${icon}.png"
sum="$(sha256sum "${work}/${icon}.png" | cut -d' ' -f1)"

if [ "${state}" = absent ] && [ ! -f "${marker}" ]; then
	echo KEPT
	exit 0
fi
if [ "${state}" = present ] && [ -f "${marker}" ] && [ "$(cat "${marker}")" = "${sum}" ]; then
	echo KEPT
	exit 0
fi

printf '"Object";"Parent";"Value";"IconFile";"ContentType"\n"%s";"";"%s";"%s.png";"image/png"\n' \
	"${icon}" "${icon}" "${icon}" >"${work}/icons.csv"

if ! log="$("${console}" Admin::ObjectIcon::Import --file "${work}/icons.csv" --icon-directory "${work}" 2>&1)"; then
	printf '%s\n' "${log}" >&2
	exit 1
fi
case "${log}" in
*"Imported 1/1 icons"*) ;;
*)
	printf '%s\n' "${log}" >&2
	exit 1
	;;
esac
case "${log}" in
*"Could not"* | *"Unable to"*)
	printf '%s\n' "${log}" >&2
	exit 1
	;;
esac

if ! log="$("${console}" Admin::ObjectIcon::SyncAllToFS 2>&1)"; then
	printf '%s\n' "${log}" >&2
	exit 1
fi

if [ "${state}" = present ]; then
	mkdir -p "${marker_dir}"
	printf '%s\n' "${sum}" >"${marker}"
else
	rm -f "${marker}"
fi
echo CONVERGED
