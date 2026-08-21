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

mapfile -t php_files < <(
	find . -type f -name '*.php' \
		-not -path './node_modules/*' \
		-not -path './vendor/*' \
		-not -path './.git/*' |
		sed 's|^\./||' | sort
)
if [[ "${#php_files[@]}" -eq 0 ]]; then
	printf 'No PHP files found.\n'
	exit 0
fi

if ! command -v php >/dev/null 2>&1; then
	printf 'SKIP: php is not installed; %d file(s) left unchecked.\n' "${#php_files[@]}"
	exit 0
fi

failed=0
for file in "${php_files[@]}"; do
	if ! php -l "${file}"; then
		failed=1
	fi
done

exit "${failed}"
