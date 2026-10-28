#!/usr/bin/env bash
# shellcheck shell=bash
#
# Prints one "<entry> <sha256>" line per top-level entry of external/ in the current directory (Wazuh's src/src after
# make deps), sorted by entry; the hash covers every file under the entry. The role compares these lines to
# WAZUH_AGENT_SOURCE_PINS, and the README's pinning steps run this script to compute them.
#
# Usage: deps_manifest.sh

set -euo pipefail

find external -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort | while IFS= read -r name; do
	printf '%s %s\n' "${name}" "$(find "external/${name}" -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
done
