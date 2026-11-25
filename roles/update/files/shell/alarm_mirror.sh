#!/usr/bin/env bash
# Param: $1 demote or retry, $2 the pacman mirrorlist. Only a mirrorlist with an active Server on the Arch Linux ARM geo host mirror.archlinuxarm.org is touched. A missing mirrorlist counts as one without that host. demote moves every geo Server behind the last concrete Server, prints the new first Server and exits 3; it exits 0 and prints nothing when nothing moved. retry moves the first concrete Server behind the last concrete one, then re-syncs the databases and upgrades, at most once for every concrete mirror after the first; it exits 0 after the upgrade that succeeded, with pacman's code when none did, and 1 when it retried nothing.
set -euo pipefail

verb="$1"
mirrorlist="$2"
server='^[[:space:]]*Server[[:space:]]*='
geo='^[[:space:]]*Server[[:space:]]*=[[:space:]]*https?://mirror\.archlinuxarm\.org/'

case "${verb}" in
demote | retry) ;;
*)
	echo "ERROR: unknown verb ${verb}, expected demote or retry" >&2
	exit 2
	;;
esac

scan() {
	local index
	geos=()
	concrete=()
	for index in "${!lines[@]}"; do
		[[ "${lines[index]}" =~ ${server} ]] || continue
		if [[ "${lines[index]}" =~ ${geo} ]]; then
			geos+=("${index}")
		else
			concrete+=("${index}")
		fi
	done
}

move_behind() {
	local from="$1" after="$2" index
	local moved=()
	for index in "${!lines[@]}"; do
		if ((index != from)); then
			moved+=("${lines[index]}")
		fi
		if ((index == after)); then
			moved+=("${lines[from]}")
		fi
	done
	lines=("${moved[@]}")
	printf '%s\n' "${lines[@]}" >"${mirrorlist}.new"
	chmod --reference="${mirrorlist}" "${mirrorlist}.new"
	chown --reference="${mirrorlist}" "${mirrorlist}.new"
	mv -f "${mirrorlist}.new" "${mirrorlist}"
	scan
}

demote_geo() {
	((${#geos[@]} > 0 && ${#concrete[@]} > 0)) || return 0
	while ((geos[0] < concrete[-1])); do
		move_behind "${geos[0]}" "${concrete[-1]}"
		demoted=1
	done
}

lead() {
	printf '%s\n' "${lines[concrete[0]]}"
}

lines=()
if [[ -f "${mirrorlist}" ]]; then
	mapfile -t lines <"${mirrorlist}"
fi
scan
demoted=0

case "${verb}" in
demote)
	demote_geo
	if ((demoted)); then
		lead
		exit 3
	fi
	;;
retry)
	((${#geos[@]} > 0)) || exit 1
	demote_geo
	status=1
	for ((rotation = 1; rotation < ${#concrete[@]}; rotation++)); do
		move_behind "${concrete[0]}" "${concrete[-1]}"
		status=0
		pacman --sync --refresh --refresh --sysupgrade --noconfirm >&2 || status=$?
		if ((status == 0)); then
			lead
			exit 0
		fi
	done
	exit "${status}"
	;;
esac
