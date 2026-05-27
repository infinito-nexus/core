#!/usr/bin/env bash
set -euo pipefail

# Usage: archive_playwright_reports.sh <reports_dir> <variant_index> <async_enabled>
#
# Move playwright-junit.xml / playwright-report/ / test-results/ from
# <reports_dir> into <reports_dir>/variant-N/{sync|async}/ so subsequent
# invocations of the test-e2e-playwright role cannot overwrite them.
# Idempotent: an existing slot is replaced rather than refused.

if [ "$#" -ne 3 ]; then
	echo "usage: $0 <reports_dir> <variant_index> <async_enabled>" >&2
	exit 2
fi

reports_dir="$1"
variant_index="$2"
async_enabled="$3"

case "$async_enabled" in
true | True | TRUE | 1) pass="async" ;;
*) pass="sync" ;;
esac

subdir="variant-${variant_index}/${pass}"

cd "$reports_dir"
mkdir -p "$subdir"
for item in playwright-junit.xml playwright-report test-results; do
	if [ -e "$item" ]; then
		rm -rf "${subdir:?}/$item"
		mv "$item" "$subdir/"
	fi
done
