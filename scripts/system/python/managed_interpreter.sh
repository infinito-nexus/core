#!/bin/sh
# shellcheck shell=sh
#
# group_vars/all/00_general.yml pins ansible_python_interpreter to
# /usr/local/bin/python3, and fact gathering is the first thing that needs it,
# so nothing inside the play can create it: a bare server fails at 'Gathering
# Facts' with "The module interpreter '/usr/local/bin/python3' was not found",
# rc 127.
#
# Runs through ansible.builtin.script, which needs no python on the target.
#
# Output: 'linked' when it created the symlink, 'present' when it did not.

set -eu

if [ -x /usr/local/bin/python3 ]; then
	echo present
	exit 0
fi

discovered="$(command -v python3 || true)"
if [ -z "${discovered}" ]; then
	echo "FAILURE: no python3 on PATH; a managed server needs one before any module can run" >&2
	exit 1
fi

mkdir -p /usr/local/bin
ln -sfn "${discovered}" /usr/local/bin/python3
echo linked
