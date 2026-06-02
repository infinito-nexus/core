#!/usr/bin/env bash
set -euo pipefail

converged=false
for i in $(seq 1 90); do
	mediawiki_replicas=$(docker exec "${MGR}" docker service ls \
		--filter "name=${STACK_NAME}_mediawiki" \
		--format '{{.Replicas}}')
	mediawiki_state=$(docker exec "${MGR}" sh -c "
    docker service ps --no-trunc \
      --format '{{.CurrentState}}' \
      ${STACK_NAME}_mediawiki \
    | head -1
  ")
	mariadb_state=$(docker exec "${MGR}" docker inspect \
		--format '{{.State.Status}}' mariadb 2>/dev/null || echo "missing")
	echo "[${i}] mw: ${mediawiki_replicas} | mw_state: ${mediawiki_state} | mariadb: ${mariadb_state}"
	if [ "${mediawiki_replicas}" = "1/1" ] &&
		echo "${mediawiki_state}" | grep -q '^Running' &&
		[ "${mariadb_state}" = "running" ]; then
		echo "Stack converged"
		converged=true
		break
	fi
	sleep 2
done

if [ "${converged}" != "true" ]; then
	echo "FAILURE: stack did not converge within timeout"
	docker exec "${MGR}" docker service ps --no-trunc "${STACK_NAME}_mediawiki" || true
	docker exec "${MGR}" docker inspect --format '{{json .State}}' mariadb || true
	exit 1
fi
