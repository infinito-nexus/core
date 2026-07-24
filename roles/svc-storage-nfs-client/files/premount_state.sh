#!/usr/bin/env bash
set -eu
: "${DIR_VAR_LIB:?DIR_VAR_LIB required}"

if mountpoint -q "${DIR_VAR_LIB}"; then
  echo "mounted"
elif [ -d "${DIR_VAR_LIB}" ] && [ -n "$(ls -A "${DIR_VAR_LIB}" 2>/dev/null)" ]; then
  echo "has-local-data"
else
  echo "empty"
fi
