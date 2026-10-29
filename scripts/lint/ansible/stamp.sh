# shellcheck shell=bash
# Param ansible_lint_fingerprint <all|yaml>: content hash of every file in the tree, or of its YAML files only.
# Param ansible_lint_stamp_matches <fingerprint>: succeeds when the last green ansible-lint run saw this fingerprint.
# Param ansible_lint_stamp_record <fingerprint>: records the fingerprint as linted green.
# Param ansible_lint_included: passes on the stdin paths that lie outside the exclude_paths of .ansible-lint.
ANSIBLE_LINT_STAMP="build/ansible-lint.stamp"

ansible_lint_fingerprint() {
	local -a only=()
	case "$1" in
	all) ;;
	yaml) only=(\( -name '*.yml' -o -name '*.yaml' \)) ;;
	*)
		printf 'ansible_lint_fingerprint: expected all or yaml, got %s\n' "$1" >&2
		return 2
		;;
	esac
	find . \( -path ./build -o -name .git -o -name node_modules -o -name __pycache__ -o -name .ansible \
		-o -name .cache -o -name .pytest_cache -o -name .ruff_cache -o -name .phpunit.result.cache \) -prune \
		-o -type f "${only[@]}" -print0 |
		LC_ALL=C sort -z |
		xargs -0 sha256sum |
		sha256sum |
		cut -d' ' -f1
}

ansible_lint_stamp_matches() {
	[[ -f "${ANSIBLE_LINT_STAMP}" && "$(<"${ANSIBLE_LINT_STAMP}")" == "$1" ]]
}

ansible_lint_stamp_record() {
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
