#!/usr/bin/env bash
#
# Inputs via env:
#   BASE_SHA  the pull-request base commit the diff is taken against.
#
# Outputs (GITHUB_OUTPUT):
#   affected=true|false  true when a changed path is under the role skeleton
#                        templates, the role skeleton renderer, a role lint or
#                        the role-structure SPOT.

set -euo pipefail

: "${BASE_SHA:?Missing BASE_SHA}"
: "${GITHUB_OUTPUT:?Missing GITHUB_OUTPUT}"

pattern='^(templates/roles/skeleton/|cli/contributing/role/|tests/lint/ansible/|tests/integration/roles/|utils/roles/mapping\.py$)'

changed="$(git diff --name-only "${BASE_SHA}" HEAD)"

if grep -qE "${pattern}" <<<"${changed}"; then
	affected=true
else
	affected=false
fi

printf 'affected=%s\n' "${affected}" >>"${GITHUB_OUTPUT}"
echo "Role skeleton contract change detected: ${affected}"
