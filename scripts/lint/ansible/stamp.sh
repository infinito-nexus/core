# shellcheck shell=bash
# Param ansible_lint_fingerprint <all|diff|yaml> [file...]: all and diff hash everything ansible-lint reads (YAML, plugins, module utils, its configuration, collection manifests, the ansible and ansible-lint versions, these lint scripts) plus the run's scope, diff with the files it lints; yaml hashes the tree's YAML files only. Fails when the tool versions cannot be read.
# Param ansible_lint_stamp_matches <fingerprint>: succeeds when the last green ansible-lint run saw this fingerprint.
# Param ansible_lint_stamp_record <fingerprint>: records the fingerprint as linted green.
# Param ansible_lint_included: passes on the stdin paths that lie outside the exclude_paths of .ansible-lint.
ANSIBLE_LINT_STAMP="build/ansible-lint.stamp"

_ansible_lint_hash_files() {
	find . \( -path ./build -o -name .git -o -name node_modules -o -name __pycache__ -o -name .ansible \
		-o -name .cache -o -name .pytest_cache -o -name .ruff_cache -o -name .phpunit.result.cache \) -prune \
		-o -type f "$@" -print0 |
		LC_ALL=C sort -z |
		xargs -0 -r sha256sum
}

_ansible_lint_tools() {
	local lint shebang root
	local -a interpreter=() roots=()
	lint="$(command -v ansible-lint)" || return 1
	IFS= read -r shebang <"${lint}"
	read -r -a interpreter <<<"${shebang#\#!}"
	[[ "${#interpreter[@]}" -gt 0 ]] || return 1
	"${interpreter[@]}" -c '
from importlib.metadata import PackageNotFoundError, version

for name in ("ansible-lint", "ansible-core"):
    print(name, version(name))
try:
    print("ansible", version("ansible"))
except PackageNotFoundError:
    print("ansible", "absent")
' || return 1
	for root in "${HOME}/.ansible/collections" /usr/share/ansible/collections; do
		if [[ -d "${root}" ]]; then
			roots+=("${root}")
		fi
	done
	if [[ "${#roots[@]}" -gt 0 ]]; then
		find "${roots[@]}" -name MANIFEST.json -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum
	fi
}

ansible_lint_fingerprint() {
	local scope="$1" tools
	shift
	case "${scope}" in
	yaml)
		_ansible_lint_hash_files \( -name '*.yml' -o -name '*.yaml' \) | sha256sum | cut -d' ' -f1
		return
		;;
	all | diff) ;;
	*)
		printf 'ansible_lint_fingerprint: expected all, diff or yaml, got %s\n' "${scope}" >&2
		return 2
		;;
	esac
	tools="$(_ansible_lint_tools)" || return 1
	{
		printf 'scope %s\n' "${scope}"
		printf 'lints %s\n' "$@"
		printf '%s\n' "${tools}"
		_ansible_lint_hash_files \( -name '*.yml' -o -name '*.yaml' -o -name '.ansible-lint*' -o -name '.yamllint*' \
			-o -name ansible.cfg -o -name MANIFEST.json -o -path './plugins/*' -o -path './library/*' -o -path './utils/*' \
			-o -path './roles/*/library/*' -o -path './roles/*/module_utils/*' -o -path './roles/*/*_plugins/*' \
			-o -path ./scripts/lint/ansible.sh -o -path './scripts/lint/ansible/*' -o -path './scripts/lint/diff/*' \)
	} | sha256sum | cut -d' ' -f1
}

ansible_lint_stamp_matches() {
	[[ -n "$1" && -f "${ANSIBLE_LINT_STAMP}" && "$(<"${ANSIBLE_LINT_STAMP}")" == "$1" ]]
}

ansible_lint_stamp_record() {
	[[ -n "$1" ]] || return 0
	mkdir -p "$(dirname "${ANSIBLE_LINT_STAMP}")"
	printf '%s\n' "$1" >"${ANSIBLE_LINT_STAMP}"
}

ansible_lint_included() {
	python3 -c '
import sys
import yaml

with open(".ansible-lint", encoding="utf-8") as handle:
    prefixes = [entry.strip("/") + "/" for entry in yaml.safe_load(handle)["exclude_paths"]]
for line in sys.stdin:
    path = line.rstrip("\n")
    if not any((path + "/").startswith(prefix) for prefix in prefixes):
        print(path)
'
}
