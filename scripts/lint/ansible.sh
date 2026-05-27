#!/usr/bin/env bash
# shellcheck shell=bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

ANSIBLE_LOCAL_TEMP="${TMPDIR:-/tmp}/infinito-ansible-local-tmp"
mkdir -p "${ANSIBLE_LOCAL_TEMP}"
export ANSIBLE_LOCAL_TEMP

ansible_args=(-i localhost -c local)
while IFS= read -r group_var_file; do
	ansible_args+=(-e "@${group_var_file}")
done < <(find group_vars/all -type f -name '*.yml' | sort)
ansible_args+=(playbook.yml --syntax-check)

ansible-playbook "${ansible_args[@]}"

if command -v ansible-lint >/dev/null 2>&1; then
	ansible-lint
else
	echo "ansible-lint not installed; skipping. Run 'make install-lint' first." >&2
fi
