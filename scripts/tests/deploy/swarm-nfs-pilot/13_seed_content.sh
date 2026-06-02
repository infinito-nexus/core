#!/usr/bin/env bash
set -euo pipefail

NODE=$(docker exec "${MGR}" sh -c "
  docker service ps --no-trunc \
    --format '{{.Node}} {{.CurrentState}}' \
    ${STACK_NAME}_mediawiki \
  | awk '\$2 == \"Running\" { print \$1; exit }'
")
if [ -z "${NODE}" ]; then
	echo "FAILURE: no running MediaWiki task on any node"
	docker exec "${MGR}" docker service ps "${STACK_NAME}_mediawiki"
	exit 1
fi
echo "MediaWiki initially scheduled on: ${NODE}"
echo "INITIAL_NODE=${NODE}" >>"$GITHUB_ENV"

docker exec "${NFS_SERVER}" sh -c \
	'echo "pre-drain marker" > /srv/nfs/mediawiki_images/.pre-drain'

# Swarm routing-mesh ingress is broken in DinD-on-DinD (no iptables/VXLAN);
# probe MediaWiki directly inside its task container.
MW_CTR=$(docker exec "${NODE}" docker ps \
	--filter "name=${STACK_NAME}_mediawiki" \
	--format '{{.ID}}' | head -1)
if [ -z "${MW_CTR}" ]; then
	echo "FAILURE: cannot locate MediaWiki container on ${NODE}"
	exit 1
fi
for i in $(seq 1 30); do
	if docker exec "${NODE}" docker exec "${MW_CTR}" \
		curl -fsS http://localhost:80/ >/dev/null 2>&1; then
		echo "MediaWiki HTTP reachable inside container after ${i}s"
		break
	fi
	sleep 2
done
