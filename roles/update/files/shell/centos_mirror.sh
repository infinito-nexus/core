#!/usr/bin/env bash
# Param: none. Rewrites the CentOS Stream and EPEL repo files in /etc/yum.repos.d in place and prints the metalink repo or EPEL file of everything it pinned; prints nothing when there is nothing left to pin, exits 1 on an EPEL file whose metalinks lack their baseurl template.
set -euo pipefail

master="https://mirror.stream.centos.org"
repo_dir="/etc/yum.repos.d"

[[ -f "${repo_dir}/centos.repo" ]] || exit 0

pin() {
	local metalink_repo="$1" path="$2" file
	for file in "${repo_dir}/centos.repo" "${repo_dir}/centos-addons.repo"; do
		[[ -f "${file}" ]] || continue
		grep -q -E "^metalink=https://mirrors\.centos\.org/metalink\?repo=${metalink_repo}&" "${file}" || continue
		sed -i -E "s|^metalink=https://mirrors\.centos\.org/metalink\?repo=${metalink_repo}&.*\$|baseurl=${master}/${path}/|" "${file}"
		echo "${metalink_repo/\[\$\]stream/\$stream}"
	done
}

declare -A directories=(
	[baseos]=BaseOS
	[appstream]=AppStream
	[crb]=CRB
	[highavailability]=HighAvailability
	[nfv]=NFV
	[rt]=RT
	[resilientstorage]=ResilientStorage
)

for name in "${!directories[@]}"; do
	directory="${directories[${name}]}"
	pin "centos-${name}-[\$]stream" "\$stream/${directory}/\$basearch/os"
	pin "centos-${name}-debug-[\$]stream" "\$stream/${directory}/\$basearch/debug/tree"
	pin "centos-${name}-source-[\$]stream" "\$stream/${directory}/source/tree"
done

pin "centos-extras-sig-extras-common-[\$]stream" "SIGs/\$stream/extras/\$basearch/extras-common"
pin "centos-extras-sig-extras-common-source-[\$]stream" "SIGs/\$stream/extras/source/extras-common"

pin_epel() {
	local file="$1" metalinks templates
	metalinks="$(awk '/^metalink=https:\/\/mirrors\.fedoraproject\.org\// { n++ } END { print n + 0 }' "${file}")"
	templates="$(awk '/^#baseurl=https:\/\/download\.example\/pub\/epel\// { n++ } END { print n + 0 }' "${file}")"
	[[ "${metalinks}" -gt 0 ]] || return 0
	if [[ "${templates}" -ne "${metalinks}" ]]; then
		echo "ERROR: ${file} has ${metalinks} Fedora metalinks but ${templates} download.example baseurl templates" >&2
		exit 1
	fi
	sed -i -E \
		-e 's|^#baseurl=https://download\.example/pub/epel/|baseurl=https://dl.fedoraproject.org/pub/epel/|' \
		-e '/^metalink=https:\/\/mirrors\.fedoraproject\.org\//d' \
		"${file}"
	echo "${file##*/}"
}

for file in "${repo_dir}"/epel*.repo; do
	[[ -f "${file}" ]] || continue
	pin_epel "${file}"
done
