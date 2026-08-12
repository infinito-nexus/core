#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

mapfile -t ruby_files < <(find . -type f -name '*.rb' 2>/dev/null | sed 's|^\./||' | sort)
if [[ "${#ruby_files[@]}" -eq 0 ]]; then
	printf 'No Ruby files found.\n'
	exit 0
fi

printf 'Checking %d Ruby file(s) with ruby -c.\n' "${#ruby_files[@]}"
printf '%s\0' "${ruby_files[@]}" | xargs -0 -n1 ruby -c >/dev/null
printf 'ruby -c OK (%d file(s))\n' "${#ruby_files[@]}"
