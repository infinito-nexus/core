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

# shellcheck source=scripts/lint/diff/files.sh
source "${SCRIPT_DIR}/diff/files.sh"

if lint_diff_active sql; then
	mapfile -t sql_files < <(lint_diff_files '\.sql$')
else
	mapfile -t sql_files < <(
		find . -type f -name '*.sql' \
			-not -path './node_modules/*' \
			-not -path './.git/*' |
			sed 's|^\./||' | sort
	)
fi
if [[ "${#sql_files[@]}" -eq 0 ]]; then
	printf 'No SQL files found.\n'
	exit 0
fi

if ! command -v sqlfluff >/dev/null 2>&1; then
	printf 'SKIP: sqlfluff is not installed; %d file(s) left unchecked.\n' "${#sql_files[@]}"
	exit 0
fi

: "${INFINITO_WORKER_CPU:?INFINITO_WORKER_CPU must be set (provided by default.env via the env loader)}"

# shellcheck disable=SC2016
printf '%s\0' "${sql_files[@]}" |
	xargs -0 -n 1 -P "${INFINITO_WORKER_CPU}" sh -c \
		'sqlfluff parse "$1" >/dev/null || { printf "%s: does not parse\n" "$1" >&2; exit 1; }' _
