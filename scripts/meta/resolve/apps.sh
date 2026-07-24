#!/usr/bin/env bash
set -euo pipefail

# Resolve the JSON list the CI matrix deploys for the current
# INFINITO_DEPLOY_MODE. The query itself (filter, coverage-first sort,
# lifecycle envelope, INFINITO_MAX_JOBS cap with 'auto') lives in
# cli.meta.ci.query, shared with the deploy-plan table. Compose and host
# emit whole role names; swarm emits per-variant "role#variant" tokens.
# variant_bundles maps the list onto matrix entries.
#
# Inputs via env (defaults live in default.env, the single source of truth):
#   INFINITO_DEPLOY_MODE           compose|swarm|host (required; workflows set it)
#   INFINITO_WHITELIST             optional space-separated app ids to keep
#   INFINITO_BLACKLIST             optional space-separated app ids to drop
#   INFINITO_MAX_JOBS              cumulative job cap; 'auto' derives it per
#                                  mode from the CI chain via cli.meta.ci.slots
#   INFINITO_DISCOVERY_SORT        complexity --sort spec (coverage-first)
#   INFINITO_REQUIRED_STORAGE      per-runner CI storage budget
#   INFINITO_APP_DISCOVERY_RUNNER  host|docker
#
# Output: JSON array to stdout (single line, always valid).

PYTHON="${PYTHON:-python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

if [[ -f "scripts/meta/env/load.sh" ]]; then
	# shellcheck source=scripts/meta/env/load.sh
	source "scripts/meta/env/load.sh"
fi

json_compact_array() {
	jq -c 'if type=="array" then . else [] end'
}

run_meta_cli() {
	case "${INFINITO_APP_DISCOVERY_RUNNER:?INFINITO_APP_DISCOVERY_RUNNER must be set}" in
	host)
		"${PYTHON}" "$@"
		;;
	docker)
		NIX_CONFIG="${NIX_CONFIG:-}" \
			INFINITO_DISTRO="${INFINITO_DISTRO}" \
			docker compose exec -T infinito "${PYTHON}" "$@"
		;;
	*)
		echo "apps.sh: unknown INFINITO_APP_DISCOVERY_RUNNER='${INFINITO_APP_DISCOVERY_RUNNER}' (expected: host|docker)" >&2
		exit 2
		;;
	esac
}

mode="${INFINITO_DEPLOY_MODE:?INFINITO_DEPLOY_MODE must be set to compose, swarm or host}"
case "$mode" in
compose | swarm | host) ;;
*)
	echo "apps.sh: INFINITO_DEPLOY_MODE must be compose, swarm or host, got '$mode'" >&2
	exit 2
	;;
esac

apps_json="$(run_meta_cli -m cli.meta.ci.query --mode "$mode" --format json)"

apps_json="$(printf '%s' "${apps_json}" | jq -c 'sort')"

if [[ -n "${GITHUB_ACTIONS:-}" && -z "${ACT:-}" ]]; then
	required_storage="${INFINITO_REQUIRED_STORAGE}"

	mapfile -t roles < <(printf '%s\n' "${apps_json}" | jq -r '.[] | split("#")[0]' | sort -u)
	if [[ "${#roles[@]}" -gt 0 ]]; then
		run_meta_cli \
			-m cli.meta.roles.applications.sufficient_storage \
			--roles "${roles[@]}" \
			--required-storage "${required_storage}" \
			--warnings \
			--format json \
			>/dev/null || true

		kept_roles="$(
			run_meta_cli \
				-m cli.meta.roles.applications.sufficient_storage \
				--roles "${roles[@]}" \
				--required-storage "${required_storage}" \
				--format json |
				json_compact_array
		)"

		apps_json="$(
			printf '%s' "${apps_json}" |
				jq -c --argjson keep "${kept_roles}" \
					'map(select(. as $t | $keep | index($t | split("#")[0]) != null))'
		)"
	fi
fi

printf '%s\n' "${apps_json}" | json_compact_array
