#!/usr/bin/env bash
set -eu
param=/sys/module/nfsv4/parameters/directory_delegations

[ -e "${param}" ] || exit 0
[ "$(cat "${param}")" = N ] && exit 0
echo N >"${param}"
echo CHANGED
