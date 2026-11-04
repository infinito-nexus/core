#!/bin/sh
# Param: $1 directory holding the Matomo release the image ships.
# Param: $2 directory holding the Matomo installation of the data volume.
# Param: $3 owner the installation's files get, as user:group.
# Output: "current <version>" when $2 already runs the release of $1, else "upgraded <old> <new>" once the release replaced the code in $2.
set -eu

source_dir="$1"
target_dir="$2"
owner="$3"

release_of() {
	sed -n "s/^[[:space:]]*\(public[[:space:]]\{1,\}\)\{0,1\}const VERSION = '\([^']*\)';.*/\2/p" "$1/core/Version.php"
}

prune_gone_files() {
	[ -d "${target_dir}/$1" ] || return 0
	(cd "${target_dir}/$1" && find . -mindepth 1 -depth) | while IFS= read -r path; do
		if [ ! -e "${source_dir}/$1/${path}" ] && [ ! -L "${source_dir}/$1/${path}" ]; then
			rm -rf "${target_dir:?}/$1/${path}"
		fi
	done
}

shipped="$(release_of "${source_dir}")"
installed="$(release_of "${target_dir}")"
if [ -z "${shipped}" ] || [ -z "${installed}" ]; then
	echo "No Matomo release declared in ${source_dir} (${shipped:-none}) or ${target_dir} (${installed:-none})." >&2
	exit 1
fi

if [ "${installed}" = "${shipped}" ]; then
	echo "current ${installed}"
	exit 0
fi

if [ "$(printf '%s\n%s\n' "${installed}" "${shipped}" | sort -V | head -n 1)" = "${shipped}" ]; then
	echo "The data volume runs Matomo ${installed}, newer than the ${shipped} this image ships; refusing to replace it." >&2
	exit 1
fi

cp -a "${source_dir}/." "${target_dir}/"
{
	printf '%s\n' core libs vendor node_modules
	(cd "${source_dir}" && find plugins -mindepth 1 -maxdepth 1 -type d)
} | while IFS= read -r tree; do
	prune_gone_files "${tree}"
done
chown -R "${owner}" "${target_dir}"
echo "upgraded ${installed} ${shipped}"
