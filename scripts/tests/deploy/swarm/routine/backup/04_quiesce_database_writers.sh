#!/usr/bin/env bash
set -euo pipefail

MODE="${1:?usage: 04_quiesce_database_writers.sh manager|worker}"

is_infrastructure_image() {
	local image="${1,,}" repository
	repository="${image##*/}"
	repository="${repository%%:*}"
	repository="${repository%%@*}"
	case "${repository}" in
	postgres | postgres_* | postgis | postgis_* | mariadb | mariadb_* | mysql | mysql_* | registry) return 0 ;;
	*) return 1 ;;
	esac
}

if [[ "${MODE}" == "manager" ]]; then
	mapfile -t STACKS < <(docker stack ls --format '{{.Name}}' | sort)
	REMOVED=()
	for stack in "${STACKS[@]}"; do
		mapfile -t IMAGES < <(docker stack services "${stack}" --format '{{.Image}}')
		keep=true
		if ((${#IMAGES[@]} < 1)); then
			keep=false
		fi
		for image in "${IMAGES[@]}"; do
			is_infrastructure_image "${image}" || keep=false
		done
		if [[ "${keep}" == "true" ]]; then
			echo "KEEP: infrastructure stack ${stack} (${IMAGES[*]})"
			continue
		fi
		docker stack rm "${stack}"
		REMOVED+=("${stack}")
	done

	deadline=$(($(date +%s) + 180))
	for stack in "${REMOVED[@]}"; do
		while [[ -n "$(docker service ls -q --filter "label=com.docker.stack.namespace=${stack}")" ]]; do
			if (($(date +%s) >= deadline)); then
				echo "FAIL: stack ${stack} still has services after quiesce timeout"
				exit 1
			fi
			sleep 2
		done
		echo "OK: removed writer stack ${stack}"
	done
elif [[ "${MODE}" != "worker" ]]; then
	echo "FAIL: unsupported quiesce mode '${MODE}'"
	exit 1
fi

STOP_CONTAINERS=()
while IFS=$'\t' read -r container_id image; do
	[[ -n "${container_id}" ]] || continue
	if ! is_infrastructure_image "${image}"; then
		STOP_CONTAINERS+=("${container_id}")
	fi
done < <(docker ps --format '{{.ID}}\t{{.Image}}')
if ((${#STOP_CONTAINERS[@]} > 0)); then
	docker stop "${STOP_CONTAINERS[@]}"
fi
echo "OK: ${MODE} runs only database engines and the local registry"
