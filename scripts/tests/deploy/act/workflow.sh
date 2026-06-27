#!/usr/bin/env bash
set -euo pipefail

: "${ACT_WORKFLOW:?ACT_WORKFLOW is not set (e.g. .github/workflows/test-environment.yml)}"
: "${ACT_EVENT:=workflow_dispatch}"
: "${ACT_JOB:=}"
: "${ACT_MATRIX:=}"
: "${ACT_CONTAINER_OPTIONS:=--privileged}"
: "${ACT_NETWORK:=host}"
: "${ACT_PULL:=false}"
: "${ACT_RM:=true}"
: "${ACT_PLATFORM_IMAGE:=catthehacker/ubuntu:act-latest}"
: "${ACT_BIND:=false}"
: "${ACT_INPUTS:=}"
: "${ACT_ENV:=}"

_act_cache_path="${ACT_ACTION_CACHE_PATH:-/tmp/actcache/act}"
_stale_mounts=$(mount | grep -E " on ${_act_cache_path}/[^ ]+ type devtmpfs " || true)
if [[ -n "${_stale_mounts}" ]]; then
	echo "ERROR: stale devtmpfs bind-mounts inside ${_act_cache_path} block act from refreshing the actions cache." >&2
	echo "Affected mountpoints:" >&2
	echo "${_stale_mounts}" | awk '{print "  " $3}' >&2
	echo "Fix (run on the host, outside the agent sandbox):" >&2
	echo "  mount | awk -v p='${_act_cache_path}/' '\$5==\"devtmpfs\" && index(\$3,p)==1 {print \$3}' | sudo xargs -r umount" >&2
	echo "  sudo rm -rf ${_act_cache_path}" >&2
	exit 3
fi

echo "=== act: workflow=${ACT_WORKFLOW} event=${ACT_EVENT} job=${ACT_JOB:-<all>} matrix=${ACT_MATRIX:-<none>} inputs=${ACT_INPUTS:-<none>} ==="

cmd=(act "${ACT_EVENT}" -W "${ACT_WORKFLOW}")
cmd+=(-P "ubuntu-latest=${ACT_PLATFORM_IMAGE}")
cmd+=(-P "ubuntu-24.04=${ACT_PLATFORM_IMAGE}")
cmd+=(-P "ubuntu-22.04=${ACT_PLATFORM_IMAGE}")
cmd+=(-P "ubuntu-20.04=${ACT_PLATFORM_IMAGE}")

if [[ -n "${ACT_JOB}" ]]; then
	cmd+=(-j "${ACT_JOB}")
fi
if [[ -n "${ACT_MATRIX}" ]]; then
	cmd+=(--matrix "${ACT_MATRIX}")
fi
if [[ -n "${ACT_INPUTS}" ]]; then
	for pair in ${ACT_INPUTS}; do
		cmd+=(--input "${pair}")
	done
fi
# Param ACT_ENV: semicolon-separated KEY=VALUE pairs forwarded to the act runner via --env (values may contain commas).
if [[ -n "${ACT_ENV}" ]]; then
	IFS=';' read -ra _act_env_pairs <<<"${ACT_ENV}"
	for pair in "${_act_env_pairs[@]}"; do
		cmd+=(--env "${pair}")
	done
fi
if [[ -n "${ACT_CONTAINER_OPTIONS}" ]]; then
	cmd+=(--container-options "${ACT_CONTAINER_OPTIONS}")
fi
if [[ -n "${ACT_NETWORK}" ]]; then
	cmd+=(--network "${ACT_NETWORK}")
fi
cmd+=(--concurrent-jobs "1")

cmd+=(--pull="${ACT_PULL}")
cmd+=(--action-offline-mode)
cmd+=(--action-cache-path "${ACT_ACTION_CACHE_PATH:-/tmp/actcache/act}")
if [[ "${ACT_RM}" == "true" ]]; then
	cmd+=(--rm)
fi
cmd+=(--cache-server-addr 127.0.0.1)
cmd+=(--artifact-server-addr 127.0.0.1)
if [[ "${ACT_BIND}" == "true" ]]; then
	cmd+=(--bind)
fi

"${cmd[@]}"
