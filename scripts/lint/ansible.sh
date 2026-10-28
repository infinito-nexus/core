#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

ANSIBLE_LOCAL_TEMP="${TMPDIR:-/tmp}/infinito-ansible-local-tmp" # nocheck: posix TMPDIR convention
mkdir -p "${ANSIBLE_LOCAL_TEMP}"
export ANSIBLE_LOCAL_TEMP

ansible_args=(-i localhost -c local)
while IFS= read -r group_var_file; do
	ansible_args+=(-e "@${group_var_file}")
done < <(find group_vars/all -type f -name '*.yml' | sort)
ansible_args+=(playbook.yml --syntax-check)

ansible-playbook "${ansible_args[@]}"

if ! command -v ansible-lint >/dev/null 2>&1; then
	echo "ansible-lint not installed; skipping. Run 'make install-lint' first." >&2
	exit 0
fi

# shellcheck source=scripts/lint/diff/files.sh
source "${SCRIPT_DIR}/diff/files.sh"
# shellcheck source=scripts/lint/ansible/stamp.sh
source "${SCRIPT_DIR}/ansible/stamp.sh"

current="$(ansible_lint_fingerprint all)"
if ansible_lint_stamp_matches "${current}"; then
	echo "ansible-lint: no file changed since the last green run; skipping"
	exit 0
fi

if lint_diff_active ansible; then
	mapfile -t yaml_files < <(lint_diff_files '\.ya?ml$' | ansible_lint_included)
	if [[ "${#yaml_files[@]}" -eq 0 ]]; then
		echo "ansible-lint: no changed YAML file; skipping"
		exit 0
	fi
	ansible-lint "${yaml_files[@]}"
	exit 0
fi

ansible-lint

ansible_lint_stamp_record "${current}"
