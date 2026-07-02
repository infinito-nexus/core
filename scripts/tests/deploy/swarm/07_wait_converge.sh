#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_context.sh"

skip_if_no_swarm_service

# With NFS shared storage the DB dep runs as its own single-replica swarm service
# (volumes on NFS, schedulable on any node), named "<dep>_<dep>" like the app
# service; empty when APP_ID has no DB dep.
DB_SERVICE=""
[ "${DB_DEP}" != "none" ] && DB_SERVICE="${DB_DEP}_${DB_DEP}"

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

	db_replicas=""
	db_state="n/a"
	if [ -n "${DB_SERVICE}" ]; then
		db_replicas=$(docker exec "${MGR}" docker service ls \
			--filter "name=${DB_SERVICE}" \
			--format '{{.Replicas}}')
		db_state=$(docker exec "${MGR}" sh -c "
      docker service ps --no-trunc \
        --format '{{.CurrentState}}' \
        ${DB_SERVICE} \
      | head -1
    ")
	fi

	echo "[${i}] ${ENTITY}: ${app_replicas} | state: ${app_state} | db(${DB_DEP}): ${db_replicas} ${db_state}"

	app_ok="false"
	if [ -n "${app_replicas}" ] &&
		echo "${app_replicas}" | grep -qE '^([0-9]+)/\1$' &&
		echo "${app_state}" | grep -q '^Running'; then
		app_ok="true"
	fi
	db_ok="true"
	if [ -n "${DB_SERVICE}" ] &&
		! { echo "${db_replicas}" | grep -qE '^([0-9]+)/\1$' &&
			echo "${db_state}" | grep -q '^Running'; }; then
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
	if [ -n "${DB_SERVICE}" ]; then
		docker exec "${MGR}" docker service ps --no-trunc "${DB_SERVICE}" || true
	fi
	exit 1
fi
