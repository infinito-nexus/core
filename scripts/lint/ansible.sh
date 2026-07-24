#!/usr/bin/env bash
# shellcheck shell=bash
# Syntax-check the playbook, then run ansible-lint behind a content
# fingerprint gate: when no file ansible-lint walks (or its config) changed
# since the last green run, the lint is skipped; any change triggers the
# full run again, so coverage never shrinks.
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

LINT_SCOPE=(roles tasks group_vars host_vars library plugins playbook.yml ansible.cfg .ansible-lint .ansible-lint-ignore)
STAMP="build/ansible-lint.stamp"

fingerprint() {
	{
		git rev-parse HEAD 2>/dev/null
		git ls-files -s -- "${LINT_SCOPE[@]}" 2>/dev/null
		git status --porcelain -- "${LINT_SCOPE[@]}" 2>/dev/null |
			awk '{print $NF}' | sort -u |
			while IFS= read -r dirty; do
				[ -f "${dirty}" ] && sha256sum "${dirty}"
			done
	} | sha256sum | cut -d' ' -f1
}

current=""
if git rev-parse HEAD >/dev/null 2>&1; then
	current="$(fingerprint)"
fi
if [[ -n "${current}" && -f "${STAMP}" && "$(cat "${STAMP}")" == "${current}" ]]; then
	echo "ansible-lint: no lintable file changed since the last green run; skipping"
	exit 0
fi

ansible-lint

if [[ -n "${current}" ]]; then
	mkdir -p "$(dirname "${STAMP}")"
	printf '%s\n' "${current}" >"${STAMP}"
fi
