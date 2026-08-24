#!/usr/bin/env bash
set -eu
: "${DIR_VAR_LIB:?DIR_VAR_LIB required}"

if grep -qF " ${DIR_VAR_LIB} " /proc/self/mountinfo; then
  echo "mounted"
elif [ -d "${DIR_VAR_LIB}" ] && [ -n "$(ls -A "${DIR_VAR_LIB}" 2>/dev/null)" ]; then
  echo "has-local-data"
else
  echo "empty"
fi
