#!/usr/bin/env bash
set -euo pipefail

# Iterate one or more roles through every deploy mode in order, stopping at the
# first failure. Inputs (env):
#   apps  - space-separated entries, each <role> or <role>#<variant> (a
#           selection token pinning one variant and no other axis); <role>
#           alone deploys variant 0. Every entry is checked against the role
#           tree before the first deploy. Both modes deploy the entry's
#           variant; a variant other than 0 names its logs
#           roundtrip-<role>-v<variant>-<mode>.log. Defaults to one role per
#           dna cluster (complexity clone == false), most complex first, when
#           unset
#   modes - mode sequence (default "compose swarm"; append "k8s" here once it exists)
#   keep  - true keeps the last entry's swarm cluster, green or failed: every
#           swarm-zombie run first reclaims the lab subnet and the act outer
#           container, so an earlier entry's kept cluster goes down when the
#           next entry's swarm step starts; empty or false lets swarm-zombie
#           release it once the rescue bundle is on the host
#   disable - comma-separated provider keys removed from the test inventory;
#             the Tor key pins the swarm step to clearnet
#   preflight - false skips swarm-zombie's disk pre-flight; empty runs it
_repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"

# shellcheck source=scripts/meta/env/load.sh
. "${_repo_root}/scripts/meta/env/load.sh"

if [ -z "${apps:-}" ]; then
	apps="$("${PYTHON}" -m cli.meta.roles.applications.complexity \
		--sort "desc weight" --filter "clone == false" --format string)"
fi
[ -n "${apps// /}" ] || {
	echo "roundtrip: no roles to run" >&2
	exit 2
}

: "${keep?keep is required: true keeps the swarm cluster of the last entry, empty or false releases it}"
: "${preflight?preflight is required: false skips the swarm disk pre-flight, empty runs it}"
modes="${modes:-compose swarm}"
_log_dir="${TMPDIR:-/tmp}" # nocheck: posix TMPDIR convention

read -ra _entries <<<"${apps//$'\n'/ }"
read -ra _modes <<<"$modes"

_checked="$("${PYTHON}" -m cli.meta.ci.roundtrip "${_entries[@]}")" || exit 2

_apps=()
_variants=()
while read -r app variant; do
	_apps+=("$app")
	_variants+=("$variant")
done <<<"$_checked"

_tor_key="$("${PYTHON}" -c "import sys; sys.path.insert(0, '${_repo_root}'); from utils.github.variant.network import TOR_SERVICE; print(TOR_SERVICE)")"
_disabled=",${disable:-},"
_disabled="${_disabled//[[:space:]]/,}"

for index in "${!_apps[@]}"; do
	app="${_apps[$index]}"
	variant="${_variants[$index]}"
	label="${app}#${variant}"
	stem="${app}"
	[ "$variant" = 0 ] || stem="${app}-v${variant}"
	app_skip="$("${PYTHON}" -c "import sys; sys.path.insert(0, '${_repo_root}'); from utils.roles.meta_lookup import get_role_skip; print(' '.join(get_role_skip('${app}')))")"
	for mode in "${_modes[@]}"; do
		if [[ " ${app_skip} " == *" ${mode} "* ]]; then
			echo "==> roundtrip: ${label} [${mode}]  SKIPPED (meta/services.yml skip)"
			continue
		fi
		log="${_log_dir}/roundtrip-${stem}-${mode}.log"
		echo "==> roundtrip: ${label} [${mode}]  (log: ${log})"
		case "$mode" in
		compose)
			make -C "$_repo_root" compose-deploy \
				mode=reinstall apps="$app" full_cycle=true variant="$variant" \
				disable="${disable:-}" 2>&1 | tee "$log"
			;;
		swarm)
			network=""
			if [[ "${_disabled}" == *",${_tor_key},"* ]]; then
				network="clearnet"
			elif "${PYTHON}" -m cli.meta.ci.validate --require-discovery --modes swarm --whitelist "${label}@swarm+multi" >/dev/null 2>&1; then
				network="multi"
			fi
			echo "==> roundtrip: ${label} [swarm] network=${network:-rotation}"
			ACT_PLATFORM_IMAGE=local/act-runner-fixed:latest \
				make -C "$_repo_root" swarm-zombie app="$app" variant="$variant" network="$network" \
				disable="${disable:-}" keep="${keep}" preflight="${preflight}" 2>&1 | tee "$log"
			marker="==> swarm drill complete: app=${app}"
			grep -qF "${marker}" "$log" || {
				echo "roundtrip: ${label} [swarm] FAILED: swarm-zombie exited 0 but the drill never completed for ${app} (marker '${marker}' absent from ${log})" >&2
				exit 1
			}
			;;
		*)
			echo "roundtrip: unknown mode '${mode}' (expected: compose | swarm)" >&2
			exit 2
			;;
		esac
	done
done

echo "==> roundtrip: all ${#_apps[@]} entry(ies) green across [${modes}]"
