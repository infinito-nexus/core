#!/usr/bin/env bash
#
# Usage: no_symlinks.sh <tree>
#   <tree>  a directory checked out from an untrusted ref; the script fails
#           when it holds a symlink, which would let a later read leave it.

set -euo pipefail

tree="${1:?Usage: no_symlinks.sh <tree>}"

mapfile -t links < <(find "${tree}" -type l -print)

if ((${#links[@]} > 0)); then
	echo "Refusing ${tree}: ${#links[@]} symlink(s) survived core.symlinks=false." >&2
	printf ' - %q\n' "${links[@]:0:20}" >&2
	exit 1
fi
echo "No symlinks under ${tree}."
