#!/usr/bin/env bash
# Run autoformat, then re-stage the files that were ALREADY staged and got
# rewritten by it, so the reformatting lands in the same commit.
#
# GUARD: only re-stage when the working tree carried no unstaged tracked
# changes before autoformat ran. Otherwise a partially-staged file's unstaged
# hunk (or unrelated unstaged edits) could be swept into the index, so the
# index is left untouched and the situation is only reported.
#
# Files that autoformat rewrote but that were NOT staged before stay unstaged
# -- only the pre-staged set is ever touched.
#
# Argv: the format command to run (default: `make autoformat`).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if [[ $# -eq 0 ]]; then
	set -- make autoformat
fi

pre_unstaged="$(git diff --name-only)"

"$@"

if [[ -n "$pre_unstaged" ]]; then
	echo "autoformat-restage: unstaged changes existed before autoformat; index left untouched." >&2
	exit 0
fi

staged="$(git diff --cached --name-only)"
if [[ -z "$staged" ]]; then
	exit 0
fi

restage="$(git diff --name-only | grep -Fxf <(printf '%s\n' "$staged") || true)"
if [[ -z "$restage" ]]; then
	exit 0
fi

printf '%s\n' "$restage" | xargs -r -d '\n' git add --
echo "autoformat-restage: re-staged reformatted file(s):" >&2
printf '  %s\n' "$restage" >&2
