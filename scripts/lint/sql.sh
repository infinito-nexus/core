#!/usr/bin/env bash
# shellcheck shell=bash
#
# Dialect comes from the nearest .sqlfluff: the repo root sets postgres, and a
# directory whose SQL targets another engine overrides it beside the files.
#
# File discovery uses find, not git ls-files: inside the compose container git
# refuses the bind-mounted repo with "detected dubious ownership", which makes
# git ls-files print nothing and turns this lint into a silent no-op.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

mapfile -t sql_files < <(
	find . -type f -name '*.sql' \
		-not -path './node_modules/*' \
		-not -path './.git/*' |
		sed 's|^\./||' | sort
)
if [[ "${#sql_files[@]}" -eq 0 ]]; then
	printf 'No SQL files found.\n'
	exit 0
fi

if ! command -v sqlfluff >/dev/null 2>&1; then
	printf 'SKIP: sqlfluff is not installed; %d file(s) left unchecked.\n' "${#sql_files[@]}"
	exit 0
fi

failed=0
for file in "${sql_files[@]}"; do
	if ! sqlfluff parse "${file}" >/dev/null; then
		printf '%s: does not parse\n' "${file}" >&2
		failed=1
	fi
done

exit "${failed}"
