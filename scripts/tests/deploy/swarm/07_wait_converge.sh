#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_context.sh"

# DB containers are stateful (service_is_stateful: true) so they run as plain
# compose containers, not swarm tasks. Their container name equals DB_DEP for
# every shipped DB role; empty when APP_ID has no DB dep.
DB_CONTAINER=""
[ "${DB_DEP}" != "none" ] && DB_CONTAINER="${DB_DEP}"

converged=false
for i in $(seq 1 90); do
	app_replicas=$(docker exec "${MGR}" docker service ls \
		--filter "name=${SERVICE_NAME}" \
		--format '{{.Replicas}}')
	app_state=$(docker exec "${MGR}" sh -c "
    docker service ps --no-trunc \
      --format '{{.CurrentState}}' \
      ${SERVICE_NAME} \
    | head -1
  ")

	db_state="n/a"
	if [ -n "${DB_CONTAINER}" ]; then
		db_state=$(docker exec "${MGR}" docker inspect \
			--format '{{.State.Status}}' "${DB_CONTAINER}" 2>/dev/null || echo "missing")
	fi

	echo "[${i}] ${ENTITY}: ${app_replicas} | state: ${app_state} | db(${DB_DEP}): ${db_state}"

	app_ok="false"
	if [ -n "${app_replicas}" ] &&
		echo "${app_replicas}" | grep -qE '^([0-9]+)/\1$' &&
		echo "${app_state}" | grep -q '^Running'; then
		app_ok="true"
	fi
	db_ok="true"
	if [ -n "${DB_CONTAINER}" ] && [ "${db_state}" != "running" ]; then
		db_ok="false"
	fi

	if [ "${app_ok}" = "true" ] && [ "${db_ok}" = "true" ]; then
		echo "Stack converged"
		converged=true
		break
	fi
	sleep 2
done

if [ "${converged}" != "true" ]; then
	echo "FAILURE: stack did not converge within timeout"
	docker exec "${MGR}" docker service ps --no-trunc "${SERVICE_NAME}" || true
	if [ -n "${DB_CONTAINER}" ]; then
		docker exec "${MGR}" docker inspect --format '{{json .State}}' "${DB_CONTAINER}" || true
	fi
	exit 1
fi
