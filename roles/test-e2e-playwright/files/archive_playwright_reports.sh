#!/usr/bin/env bash
set -euo pipefail

# Usage: archive_playwright_reports.sh <reports_dir> <variant_index> <update_pass>
#
# Move playwright-junit.xml / playwright-report/ / test-results/ and the
# parallel scheduler's run-parallel/ (output and result of the run) from
# <reports_dir> into <reports_dir>/variant-N/{initial|update}/ so subsequent
# invocations of the test-e2e-playwright role cannot overwrite them.
# Idempotent: an existing slot is replaced rather than refused.

if [ "$#" -ne 3 ]; then
	echo "usage: $0 <reports_dir> <variant_index> <update_pass>" >&2
	exit 2
fi

reports_dir="$1"
variant_index="$2"
update_pass="$3"

case "$update_pass" in
true | True | TRUE | 1) pass="update" ;;
*) pass="initial" ;;
esac

subdir="variant-${variant_index}/${pass}"

cd "$reports_dir"
rm -rf "${subdir:?}"
mkdir -p "$subdir"
for item in playwright-junit.xml playwright-report test-results run-parallel; do
	if [ -e "$item" ]; then
		mv "$item" "$subdir/"
	fi
done
