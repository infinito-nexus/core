# shellcheck shell=bash
# Param lint_diff_write <type>: on the host, writes build/lint-diff-<type>.txt with every file changed since the merge-base of HEAD and INFINITO_LINT_DIFF_BASE (untracked files and pulled custom roles included) and prints its path; prints nothing when every file must be linted.
# Param lint_diff_active <ansible|javascript|markdown|mermaid|shellcheck|sql>: succeeds when LINT_DIFF_FILES names a list and none of its files is configuration of that tool or a shared lint script.
# Param lint_diff_files <regex>: prints the listed files matching <regex> that still exist, one per line.
# Param lint_custom_roles: prints every pulled custom role directory (roles/web-app-cst-*), one per line; Git ignores them, so tools that honour .gitignore get them passed explicitly.

lint_custom_roles() {
	find roles -mindepth 1 -maxdepth 1 -type d -name 'web-app-cst-*' -print | LC_ALL=C sort
}

lint_diff_write() {
	local list="build/lint-diff-$1.txt" merge_base
	if [[ -n "${GITHUB_ACTIONS:-}" || -z "${INFINITO_LINT_DIFF_BASE:-}" ]]; then
		return 0
	fi
	if ! merge_base="$(git merge-base HEAD "${INFINITO_LINT_DIFF_BASE}" 2>/dev/null)"; then
		echo "lint $1: no merge-base with ${INFINITO_LINT_DIFF_BASE}; checking every file" >&2
		return 0
	fi
	mkdir -p build
	{
		git diff --name-only --diff-filter=d "${merge_base}"
		git ls-files --others --exclude-standard
		lint_custom_roles | xargs -r -d '\n' -I{} find {} -type f -print
	} | LC_ALL=C sort -u >"${list}"
	echo "lint $1: $(wc -l <"${list}") file(s) changed since ${INFINITO_LINT_DIFF_BASE}; ansible, javascript, markdown, mermaid, shellcheck and sql check only those unless their configuration changed" >&2
	printf '%s\n' "${list}"
}

lint_diff_active() {
	local list="${LINT_DIFF_FILES:-}" trigger
	case "$1" in
	ansible) trigger='^(\.ansible-lint|\.ansible-lint-ignore|ansible\.cfg|requirements/[^/]+\.ya?ml|scripts/lint/ansible\.sh|scripts/lint/ansible/.*)$' ;;
	javascript) trigger='^(eslint\.config\.js|package\.json|package-lock\.json|scripts/lint/javascript\.sh)$' ;;
	markdown) trigger='(^|/)\.markdownlint[^/]*$|^scripts/lint/markdown\.sh$' ;;
	mermaid) trigger='^scripts/lint/mermaid\.sh$' ;;
	shellcheck) trigger='(^|/)\.shellcheckrc$|^scripts/lint/shellcheck\.sh$' ;;
	sql) trigger='(^|/)\.sqlfluff$|^scripts/lint/sql\.sh$' ;;
	*)
		echo "lint_diff_active: unknown tool '$1'" >&2
		return 2
		;;
	esac
	[[ -n "${list}" && -f "${list}" ]] || return 1
	if grep -qE "${trigger}|^scripts/lint/(wrapper|autoformat)\.sh$|^scripts/lint/diff/" "${list}"; then
		return 1
	fi
}

lint_diff_files() {
	local file
	{ grep -E "$1" "${LINT_DIFF_FILES}" || [[ $? -eq 1 ]]; } | while IFS= read -r file; do
		if [[ -f "${file}" ]]; then
			printf '%s\n' "${file}"
		fi
	done
}
