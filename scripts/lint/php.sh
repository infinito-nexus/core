#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

mapfile -t php_files < <(find . -type f -name '*.php' 2>/dev/null | sed 's|^\./||' | sort)
if [[ "${#php_files[@]}" -eq 0 ]]; then
	printf 'No PHP files found.\n'
	exit 0
fi

printf 'Checking %d PHP file(s) with php -l.\n' "${#php_files[@]}"
printf '%s\0' "${php_files[@]}" | xargs -0 -n1 php -l >/dev/null
printf 'php -l OK (%d file(s))\n' "${#php_files[@]}"
