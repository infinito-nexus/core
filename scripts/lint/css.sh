#!/usr/bin/env bash
# shellcheck shell=bash
#
# stylelint reports a CssSyntaxError whatever the rule set says, so the empty
# config in .stylelintrc.json is enough to make this a parse check and keeps it
# from turning into a style opinion nobody signed up for.
#
# File discovery uses find, not git ls-files: inside the compose container git
# refuses the bind-mounted repo with "detected dubious ownership", which makes
# git ls-files print nothing and turns this lint into a silent no-op.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

mapfile -t css_files < <(
	find . -type f -name '*.css' \
		-not -path './node_modules/*' \
		-not -path './.git/*' |
		sed 's|^\./||' | sort
)
if [[ "${#css_files[@]}" -eq 0 ]]; then
	printf 'No CSS files found.\n'
	exit 0
fi

if [[ ! -d node_modules/stylelint ]]; then
	printf 'SKIP: stylelint is not installed; %d file(s) left unchecked.\n' "${#css_files[@]}"
	exit 0
fi

npx --no-install stylelint "${css_files[@]}"
