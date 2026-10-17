#!/usr/bin/env bash
set -euo pipefail

ready_seconds="${1:?ready_seconds required}"
poll_seconds="${2:?poll_seconds required}"
allocation_timeout_seconds="${3:?allocation_timeout_seconds required}"
shift 3
[ "$#" -gt 0 ] || {
	echo "search_allocation_precheck: entrypoint required" >&2
	exit 2
}

base="${ELASTICSEARCH_SCHEMA:?}://${ELASTICSEARCH_HOST:?}:${ELASTICSEARCH_PORT:?}"
probe="${ELASTICSEARCH_NAMESPACE:?}_allocation_probe_${HOSTNAME,,}"

deadline=$(($(date +%s) + ready_seconds))
until curl -fsS --connect-timeout 5 --max-time 10 -o /dev/null "${base}/_cluster/health"; do
	if [ "$(date +%s)" -ge "$deadline" ]; then
		echo "search_allocation_precheck: ${base} did not answer within ${ready_seconds}s" >&2
		exit 1
	fi
	sleep "$poll_seconds"
done

curl -fsS --connect-timeout 5 --max-time 30 -o /dev/null -X DELETE "${base}/${probe}?ignore_unavailable=true"
created=$(curl -sS --connect-timeout 5 --max-time "$((allocation_timeout_seconds + 30))" -X PUT "${base}/${probe}?wait_for_active_shards=1&timeout=${allocation_timeout_seconds}s" \
	-H 'Content-Type: application/json' \
	-d '{"settings":{"index":{"number_of_shards":1,"number_of_replicas":0}}}')
if ! grep -q '"shards_acknowledged":true' <<<"$created"; then
	{
		echo "search_allocation_precheck: Elasticsearch allocated no primary shard for ${probe} within ${allocation_timeout_seconds}s"
		echo "$created"
		curl -sS --connect-timeout 5 --max-time 30 "${base}/_cluster/allocation/explain" \
			-H 'Content-Type: application/json' \
			-d "{\"index\":\"${probe}\",\"shard\":0,\"primary\":true}"
		echo
	} >&2
	curl -sS --connect-timeout 5 --max-time 30 -o /dev/null -X DELETE "${base}/${probe}"
	exit 1
fi
curl -fsS --connect-timeout 5 --max-time 30 -o /dev/null -X DELETE "${base}/${probe}"
echo "search_allocation_precheck: Elasticsearch allocates shards, starting $1"
exec "$@"
