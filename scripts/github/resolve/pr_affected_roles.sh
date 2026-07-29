#!/usr/bin/env bash
#
# Resolve the role whitelist for a pull-request CI run and write
# `whitelist` to GITHUB_OUTPUT. This is the single entry point the
# `detect-affected-roles` job calls; it keeps the subset-vs-diff
# selection logic out of the workflow YAML.
#
# Inputs via env:
#   SUBSET_LABELED  "true" when the PR carries the '🧩 Subset' label.
#                   When set, the explicit role list declared in the PR
#                   body wins, resolved by the cli.meta.ci.subset_roles
#                   module (strict: it fails the run on
#                   invalid/empty/unknown roles).
#                   Otherwise the diff-derived resolver runs unchanged.
#   PR_BODY         PR body markdown (only read on the subset path).
#
# Outputs (GITHUB_OUTPUT):
#   whitelist=<role-id ...|__ALL__>

set -euo pipefail

: "${GITHUB_OUTPUT:?Missing GITHUB_OUTPUT}"

if [[ "${SUBSET_LABELED:-}" == "true" ]]; then
	echo "🧩 Subset label present: restricting CI to the roles listed in the PR body."
	# shellcheck source=scripts/meta/env/load.sh
	source "scripts/meta/env/load.sh"
	exec "${PYTHON}" -m cli.meta.ci.subset_roles
fi

resolved="$(./scripts/meta/resolve/diff/affected_roles.sh)"
echo "Resolver output: ${resolved}"
printf 'whitelist=%s\n' "${resolved}" >>"${GITHUB_OUTPUT}"
