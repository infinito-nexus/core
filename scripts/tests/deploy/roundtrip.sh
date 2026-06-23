#!/usr/bin/env bash
set -euo pipefail

# Iterate one or more roles through every deploy mode in order, stopping at the
# first failure. Inputs (env):
#   apps  - space-separated role ids (required)
#   modes - mode sequence (default "compose swarm"; append "k8s" here once it exists)
#   keep  - true keeps each validated swarm cluster instead of releasing it
: "${apps:?apps=\"<app> [app...]\" required}"
modes="${modes:-compose swarm}"

_repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
_log_dir="${TMPDIR:-/tmp}"

read -ra _apps <<<"$apps"
read -ra _modes <<<"$modes"

for app in "${_apps[@]}"; do
	for mode in "${_modes[@]}"; do
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
