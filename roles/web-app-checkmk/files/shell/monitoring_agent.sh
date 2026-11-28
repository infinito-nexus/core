#!/bin/sh
# Param: $1  the private key file of the platform monitoring key, generated once and never read out
# Param: $2  the agent datasource program to install
# Param: stdin  the content of that program
# Prints the public key line, then CHANGED or UNCHANGED.
set -eu

key="$1"
program="$2"
changed=UNCHANGED

install -d -m 0700 "$(dirname "${key}")"
if [ ! -f "${key}" ]; then
	ssh-keygen -q -t ed25519 -N '' -C infinito-monitoring -f "${key}"
	changed=CHANGED
fi
chmod 0600 "${key}"

install -d -m 0755 "$(dirname "${program}")"
staged="$(mktemp "${program}.XXXXXX")"
cat >"${staged}"
if cmp -s "${staged}" "${program}"; then
	rm -f "${staged}"
else
	chmod 0755 "${staged}"
	mv -f "${staged}" "${program}"
	changed=CHANGED
fi

cut -d ' ' -f 1,2 "${key}.pub"
echo "${changed}"
