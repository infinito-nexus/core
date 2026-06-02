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

echo "=== act: workflow=${ACT_WORKFLOW} event=${ACT_EVENT} job=${ACT_JOB:-<all>} matrix=${ACT_MATRIX:-<none>} ==="

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
if [[ -n "${ACT_CONTAINER_OPTIONS}" ]]; then
	cmd+=(--container-options "${ACT_CONTAINER_OPTIONS}")
fi
if [[ -n "${ACT_NETWORK}" ]]; then
	cmd+=(--network "${ACT_NETWORK}")
fi
cmd+=(--concurrent-jobs "1")

cmd+=(--pull="${ACT_PULL}")
if [[ "${ACT_RM}" == "true" ]]; then
	cmd+=(--rm)
fi
cmd+=(--cache-server-addr 127.0.0.1)
cmd+=(--artifact-server-addr 127.0.0.1)
if [[ "${ACT_BIND}" == "true" ]]; then
	cmd+=(--bind)
fi

"${cmd[@]}"
