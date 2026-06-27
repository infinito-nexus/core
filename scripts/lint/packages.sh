#!/usr/bin/env bash
# shellcheck shell=bash
#
# Validate the generated distro packaging metadata with each ecosystem's
# native parser, so a malformed changelog/spec/PKGBUILD is caught here
# instead of failing the (expensive) package build in build-ci-images.
#
# Strictness: several of these parsers emit a *warning* and still exit 0
# (dpkg-parsechangelog on trailing junk, rpmspec on a bad date). This
# lint therefore fails on any parser stderr, not just on a non-zero exit,
# so warnings cannot slip through. The generator that writes these files
# (cli.contributing.changelog.archive.package_mirror) is additionally
# covered by unit tests, so prevention does not depend on tool
# availability alone.
#
# Each validator is used when its tool is on PATH and skipped with a
# notice when not, so the check runs in any single-distro lint
# environment (Debian CI validates debian/ + fedora/, an Arch host
# validates arch/ with namcap).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

status=0

run_strict() { # label cmd...
	local label="$1"
	shift
	local err rc=0
	err="$("$@" 2>&1 1>/dev/null)" || rc=$?
	if [[ ${rc} -ne 0 || -n "${err}" ]]; then
		if [[ -n "${err}" ]]; then
			printf '%s\n' "${err}" >&2
		fi
		printf '    FAILED (%s)\n' "${label}" >&2
		status=1
	else
		printf '    OK (%s)\n' "${label}"
	fi
}

echo ">>> debian/changelog"
if command -v dpkg-parsechangelog >/dev/null 2>&1; then
	run_strict "dpkg-parsechangelog --all" \
		dpkg-parsechangelog --all -l packaging/debian/changelog
else
	echo "    SKIP: dpkg-parsechangelog not installed (Debian dpkg-dev)"
fi

echo ">>> fedora/infinito-nexus.spec"
if command -v rpmspec >/dev/null 2>&1; then
	run_strict "rpmspec --parse" \
		rpmspec -P packaging/fedora/infinito-nexus.spec
else
	echo "    SKIP: rpmspec not installed (rpm)"
fi

echo ">>> arch/PKGBUILD"
run_strict "bash -n syntax" bash -n packaging/arch/PKGBUILD
if command -v namcap >/dev/null 2>&1; then
	echo "    namcap report (informational):"
	namcap packaging/arch/PKGBUILD || true # exit code unreliable → not gating
else
	echo "    SKIP: namcap not installed (informational PKGBUILD lint)"
fi

exit "${status}"
