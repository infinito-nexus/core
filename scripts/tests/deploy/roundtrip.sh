#!/usr/bin/env bash
set -euo pipefail

# Iterate one or more roles through every deploy mode in order, stopping at the
# first failure. Inputs (env):
#   apps  - space-separated role ids; defaults to one role per base cluster
#           (complexity --unique), most complex first, when unset
#   modes - mode sequence (default "compose swarm"; append "k8s" here once it exists)
#   keep  - true keeps each validated swarm cluster instead of releasing it
_repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"

# shellcheck source=scripts/meta/env/load.sh
. "${_repo_root}/scripts/meta/env/load.sh"

if [ -z "${apps:-}" ]; then
	apps="$("${PYTHON}" -m cli.meta.roles.applications.complexity \
		--sort total --order desc --unique --format string)"
fi
[ -n "${apps// /}" ] || {
	echo "roundtrip: no roles to run" >&2
	exit 2
}

modes="${modes:-compose swarm}"
_log_dir="${TMPDIR:-/tmp}"

# `complexity --format string` emits one role per line; normalise newlines to
# spaces so the no-apps default iterates every role, not just the first line.
read -ra _apps <<<"${apps//$'\n'/ }"
read -ra _modes <<<"$modes"

for app in "${_apps[@]}"; do
	# A role's meta/services.yml `skip` list opts it out of given deploy modes
	# (same SPOT the CI discovery honours via apps.sh); honour it here too.
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
				make -C "$_repo_root" act-swarm-zombie app="$app" 2>&1 | tee "$log"
			# A failure above exits via set -e and leaves the cluster up for inspection;
			# only a passing run reaches here, so release it unless keep=true.
			[ "${keep:-false}" = true ] || make -C "$_repo_root" act-swarm-down name="$app"
			;;
		*)
			echo "roundtrip: unknown mode '${mode}' (expected: compose | swarm)" >&2
			exit 2
			;;
		esac
	done
done

echo "==> roundtrip: all ${#_apps[@]} role(s) green across [${modes}]"
