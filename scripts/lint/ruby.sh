#!/usr/bin/env bash
# shellcheck shell=bash
#
# File discovery uses find, not git ls-files: inside the compose container git
# refuses the bind-mounted repo with "detected dubious ownership", which makes
# git ls-files print nothing and turns this lint into a silent no-op.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

mapfile -t ruby_files < <(
	find . -type f -name '*.rb' \
		-not -path './node_modules/*' \
		-not -path './.git/*' |
		sed 's|^\./||' | sort
)
if [[ "${#ruby_files[@]}" -eq 0 ]]; then
	printf 'No Ruby files found.\n'
	exit 0
fi

if ! command -v ruby >/dev/null 2>&1; then
	printf 'SKIP: ruby is not installed; %d file(s) left unchecked.\n' "${#ruby_files[@]}"
	exit 0
fi

failed=0
for file in "${ruby_files[@]}"; do
	if ! ruby -c "${file}" >/dev/null; then
		printf '%s: does not parse\n' "${file}" >&2
		failed=1
	fi
done

exit "${failed}"
