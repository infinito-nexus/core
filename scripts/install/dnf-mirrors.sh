#!/usr/bin/env bash
# CentOS' metalink carries its own sha512 for repomd.xml, so the digest and
# the bytes arrive from two sources that can disagree; when they do, every
# mirror fails the checksum and no retry clears it. The mirrorlist serves the
# same mirrors with no second digest to contradict them, giving up the
# metalink's integrity check on repomd.xml while packages stay GPG-verified.
# Fedora ships the same metalink shape unaffected, so it is left alone.
set -euo pipefail

shopt -s nullglob
repos=(/etc/yum.repos.d/*.repo)
if [[ ${#repos[@]} -eq 0 ]]; then
	exit 0
fi

sed -i -E 's#^metalink=(https?://mirrors\.centos\.org)/metalink\?#mirrorlist=\1/mirrorlist?#' "${repos[@]}"
