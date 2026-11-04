#!/usr/bin/env bash
# Output: amd64 | arm64 on stdout.
# Exits non-zero on a machine this project has no name for.
set -euo pipefail

machine="$(uname -m)"
case "${machine}" in
x86_64 | amd64) echo "amd64" ;;
aarch64 | arm64) echo "arm64" ;;
*)
	echo "architecture.sh: no project name for machine '${machine}'; declare it in utils/github/variant/pools.py ARCHITECTURES first." >&2
	exit 1
	;;
esac
