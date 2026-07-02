#!/usr/bin/env bash
set -euo pipefail

# Resolve the JSON list of application roles the CI matrix deploys for the
# current INFINITO_DEPLOY_MODE, via the complexity report: it filters to the
# mode's tested+invokable roles (the 'compose'/'swarm' column already bakes in
# invokable + tested-lifecycle + per-mode skip), orders them coverage-first
# (uncovered roles before ones a peer already embeds), and hard-caps the
# cumulative per-mode job budget (--max-jobs over 'bundles', the runner count).
# Whole role names are emitted; variant_bundles expands them into the matrix.
#
# Inputs via env (defaults live in default.env, the single source of truth):
#   INFINITO_DEPLOY_MODE           compose|swarm (required; workflows set it)
#   INFINITO_WHITELIST             optional space-separated app ids to keep
#   INFINITO_MAX_JOBS              cumulative job cap
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

mode="${INFINITO_DEPLOY_MODE:?INFINITO_DEPLOY_MODE must be set to compose or swarm}"
case "$mode" in
compose | swarm) ;;
*)
	echo "apps.sh: INFINITO_DEPLOY_MODE must be compose or swarm, got '$mode'" >&2
	exit 2
	;;
esac

filter="${mode} == true"
if [[ -n "${INFINITO_WHITELIST// /}" ]]; then
	wl_csv="$(printf '%s' "${INFINITO_WHITELIST}" | tr -s ' ' ',')"
	wl_csv="${wl_csv#,}"
	wl_csv="${wl_csv%,}"
	filter="${filter} and name %% {${wl_csv}}"
fi

unique_args=()
if [[ "$mode" == "compose" ]]; then
	unique_args=(--unique)
fi

apps_json="$(
	run_meta_cli \
		-m cli.meta.roles.applications.complexity \
		--deploy-mode "$mode" \
		"${unique_args[@]}" \
		--filter "$filter" \
		--sort "${INFINITO_DISCOVERY_SORT}" \
		--max-jobs "${INFINITO_MAX_JOBS}" \
		--format string |
		jq -R -s -c 'split("\n") | map(select(length>0))'
)"

apps_json="$(printf '%s' "${apps_json}" | jq -c 'sort')"

if [[ -n "${GITHUB_ACTIONS:-}" && -z "${ACT:-}" ]]; then
	required_storage="${INFINITO_REQUIRED_STORAGE}"

	mapfile -t roles < <(printf '%s\n' "${apps_json}" | jq -r '.[]')
	if [[ "${#roles[@]}" -gt 0 ]]; then
		run_meta_cli \
			-m cli.meta.roles.applications.sufficient_storage \
			--roles "${roles[@]}" \
			--required-storage "${required_storage}" \
			--warnings \
			--format json \
			>/dev/null || true

		apps_json="$(
			run_meta_cli \
				-m cli.meta.roles.applications.sufficient_storage \
				--roles "${roles[@]}" \
				--required-storage "${required_storage}" \
				--format json |
				json_compact_array
		)"
	fi
fi

printf '%s\n' "${apps_json}" | json_compact_array
