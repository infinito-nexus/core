#!/usr/bin/env bash
#
# Compute which roles are affected by the current branch's diff against
# `origin/main`, expanded transitively over run_after + dependencies +
# services edges via cli.meta.roles.applications.resolution.affected.
#
# Output (single line on stdout):
#   __ALL__                          full deploy needed. Emitted when:
#                                      * the diff is empty, OR
#                                      * any changed path outside
#                                        roles/<role>/ is not a Markdown
#                                        or reStructuredText file (the
#                                        `.md`/`.rst` skip-list mirrors
#                                        scripts/meta/resolve/pr/scope.sh's
#                                        `is_markdown_or_rst`), OR
#                                      * the diff contains only such
#                                        skipped paths and no role seeds
#                                        could be derived, OR
#                                      * any seed role is non-modellable
#                                        in the reverse resolver
#                                        (resolver exit 2), OR
#                                      * the resolver itself errors out
#                                        (any other non-zero exit).
#   <role-id> [<role-id> ...]        restricted deploy set (whitelist).
#
# Pre-conditions:
#   - The host Python interpreter referenced by ${PYTHON:-python3} has the
#     project's resolver deps installed (e.g. via `make install`).
#   - `git fetch origin main` is reachable (caller already did checkout).
#
# Exit codes:
#   0 in all defined output cases (including the fail-safe __ALL__).
#   The script is fail-safe by design: any resolver failure widens the
#   deploy matrix to "all", it never narrows it.

set -euo pipefail

PYTHON="${PYTHON:-python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

if [[ -f "scripts/meta/env/load.sh" ]]; then
	# shellcheck source=scripts/meta/env/load.sh
	source "scripts/meta/env/load.sh"
fi

emit_all() {
	echo "__ALL__"
	exit 0
}

git fetch --quiet --no-tags --prune --depth=50 origin main >/dev/null 2>&1 ||
	git fetch --quiet --no-tags --prune origin main

if base="$(git merge-base origin/main HEAD 2>/dev/null)"; then
	mapfile -t changed_paths < <(git diff --name-only "${base}" HEAD --)
else
	mapfile -t changed_paths < <(git diff --name-only origin/main HEAD --)
fi

if ((${#changed_paths[@]} == 0)); then
	emit_all
fi

declare -A seed_roles=()

for path in "${changed_paths[@]}"; do
	[[ -z "${path}" ]] && continue
	if [[ "${path}" != roles/*/* ]]; then
		case "${path}" in
		*.md | *.rst)
			continue
			;;
		esac
		emit_all
	fi
	role="${path#roles/}"
	role="${role%%/*}"
	[[ -z "${role}" ]] && emit_all
	seed_roles["${role}"]=1
done

if ((${#seed_roles[@]} == 0)); then
	emit_all
fi

mapfile -t seed_list < <(printf '%s\n' "${!seed_roles[@]}" | sort)

set +e
resolved="$(
	"${PYTHON}" -m cli.meta.roles.applications.resolution.affected \
		--changed-roles "${seed_list[@]}"
)"
resolver_rc=$?
set -e

# Exit 2 means "non-modellable seed; fall back to full deploy".
# Any other non-zero is a resolver/runtime error; we still fail-safe to
# __ALL__ rather than risk silently shrinking the deploy matrix.
if ((resolver_rc != 0)); then
	emit_all
fi

resolved="${resolved//$'\r'/}"
resolved="${resolved#"${resolved%%[![:space:]]*}"}"
resolved="${resolved%"${resolved##*[![:space:]]}"}"

if [[ -z "${resolved}" ]]; then
	emit_all
fi

printf '%s\n' "${resolved}"
