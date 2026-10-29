#!/usr/bin/env sh
# Usage: build-trust-bundle.sh <bundle> <source>...
#   bundle  file to hold the concatenated sources; rewritten in place, keeping its inode for
#           containers that bind-mount it, and only when its content differs
#   source  certificate files, concatenated in the given order
# Prints "bundle-rewritten" when the bundle was replaced.
set -eu

bundle="$1"
shift

staged="$(mktemp "${bundle}.XXXXXX")"
trap 'rm -f "$staged"' EXIT

cat "$@" >"$staged"
if ! cmp -s "$staged" "$bundle"; then
  cat "$staged" >"$bundle"
  echo "bundle-rewritten"
fi
