#!/usr/bin/env bash
set -euo pipefail

shopt -s nullglob
repos=(/etc/yum.repos.d/*.repo)
if [[ ${#repos[@]} -eq 0 ]]; then
	exit 0
fi

upstream='https://mirror.stream.centos.org'

# Param: $1 repo id as the metalink query spells it, $2 directory on the upstream
for_repo() {
	sed -i -E \
		"s#^metalink=https?://mirrors\\.centos\\.org/metalink\\?repo=centos-$1-([^-&]+)-stream.*#baseurl=$upstream/\\1-stream/$2/\\\$basearch/os/#" \
		"${repos[@]}"
}

for_repo baseos BaseOS
for_repo appstream AppStream

sed -i -E \
	"s#^metalink=https?://mirrors\\.centos\\.org/metalink\\?repo=centos-extras-sig-extras-common-([^-&]+)-stream.*#baseurl=$upstream/SIGs/\\1-stream/extras/\\\$basearch/extras-common/#" \
	"${repos[@]}"
