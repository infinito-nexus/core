#!/usr/bin/env bash
# Param: $1 source tree to copy
# Param: $2 build workspace, removed and recreated empty
# Param: $3... exclusion patterns, unanchored, so `.git` drops every `.git` at any depth
set -euo pipefail

src="${1:?usage: stage.sh SRC DEST [EXCLUDE...]}"
dest="${2:?usage: stage.sh SRC DEST [EXCLUDE...]}"
shift 2

excludes=()
for pattern in "$@"; do
	excludes+=("--exclude=${pattern}")
done

rm -rf "${dest}"
mkdir -p "${dest}"
tar -C "${src}" "${excludes[@]}" --format=posix -cf - . | tar -C "${dest}" -xf -
