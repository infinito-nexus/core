#!/usr/bin/env bash
# shellcheck shell=bash
set -uo pipefail

if [[ -f "${HOME}/.lmstudio-home-pointer" ]]; then
	lm_home="$(<"${HOME}/.lmstudio-home-pointer")"
elif [[ -d "${HOME}/.cache/lm-studio" ]]; then
	lm_home="${HOME}/.cache/lm-studio"
else
	lm_home="${HOME}/.lmstudio"
fi

started="$(date +%s%N)"
/app/llmster --docker-compatible-platforms --start-timestamp "${started}" &
llmster_pid=$!

shutdown() {
	kill -TERM "${llmster_pid}" 2>/dev/null
	wait "${llmster_pid}"
	exit 0
}
trap shutdown TERM INT

deadline=$(($(date +%s) + 300))
until [[ -f "${lm_home}/.ready-${started}" ]]; do
	if (($(date +%s) >= deadline)); then
		echo "llmster wrote no ready marker within 300 seconds" >&2
		break
	fi
	sleep 1
done

/app/.bundle/lms server start --port "${LMSTUDIO_PORT}" --quiet
status=$?
if ((status != 0)); then
	exit "${status}"
fi

wait "${llmster_pid}"
