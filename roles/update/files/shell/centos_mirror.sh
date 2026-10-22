#!/usr/bin/env bash
# Param: none. Rewrites the CentOS Stream repo files in /etc/yum.repos.d in place and prints the metalink repo of every section it pinned; prints nothing when there is nothing left to pin.
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
