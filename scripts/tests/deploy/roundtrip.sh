#!/usr/bin/env bash
set -euo pipefail

# Iterate one or more roles through every deploy mode in order, stopping at the
# first failure. Inputs (env):
#   apps  - space-separated role ids; defaults to one role per dna cluster
#           (complexity clone == false), most complex first, when unset
#   modes - mode sequence (default "compose swarm"; append "k8s" here once it exists)
#   keep  - true keeps each validated swarm cluster instead of releasing it
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

modes="${modes:-compose swarm}"
_log_dir="${TMPDIR:-/tmp}" # nocheck: posix TMPDIR convention

read -ra _apps <<<"${apps//$'\n'/ }"
read -ra _modes <<<"$modes"

for app in "${_apps[@]}"; do
	app_skip="$("${PYTHON}" -c "import sys; sys.path.insert(0, '${_repo_root}'); from utils.roles.meta_lookup import get_role_skip; print(' '.join(get_role_skip('${app}')))")"
	for mode in "${_modes[@]}"; do
		if [[ " ${app_skip} " == *" ${mode} "* ]]; then
			echo "==> roundtrip: ${app} [${mode}]  SKIPPED (meta/services.yml skip)"
			continue
		fi
		log="${_log_dir}/roundtrip-${app}-${mode}.log"
		echo "==> roundtrip: ${app} [${mode}]  (log: ${log})"
		case "$mode" in
		compose)
			make -C "$_repo_root" compose-deploy \
				mode=reinstall apps="$app" full_cycle=true variant=0 2>&1 | tee "$log"
			;;
		swarm)
			ACT_PLATFORM_IMAGE=local/act-runner-fixed:latest \
				make -C "$_repo_root" swarm-zombie app="$app" 2>&1 | tee "$log"
			grep -q "Matrix-deploy ${app}: provision/deploy/e2e/verify per round" "$log" || {
				echo "roundtrip: ${app} [swarm] FAILED: swarm deploy job did not run (empty matrix); see ${log}" >&2
				exit 1
			}
			[ "${keep:-false}" = true ] || make -C "$_repo_root" swarm-down name="$app"
			;;
		*)
			echo "roundtrip: unknown mode '${mode}' (expected: compose | swarm)" >&2
			exit 2
			;;
		esac
	done
done

echo "==> roundtrip: all ${#_apps[@]} role(s) green across [${modes}]"
