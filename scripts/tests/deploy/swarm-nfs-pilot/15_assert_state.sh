#!/usr/bin/env bash
set -euo pipefail

REPL=""
for i in $(seq 1 60); do
	REPL=$(docker exec "${MGR}" docker service ls \
		--filter "name=${STACK_NAME}_mediawiki" --format '{{.Replicas}}')
	echo "[${i}] mediawiki replicas: ${REPL}"
	if [ "${REPL}" = "1/1" ]; then
		break
	fi
	sleep 2
done
[ "${REPL}" = "1/1" ] || {
	echo "Replicas != 1/1: ${REPL}"
	exit 1
}

docker exec "${NEW_NODE}" sh -c "
  mkdir -p /mnt/nfs-check
  mount -t nfs -o vers=3,nolock ${NFS_IP}:/srv/nfs /mnt/nfs-check
  grep -q 'pre-drain marker' /mnt/nfs-check/mediawiki_images/.pre-drain
  umount /mnt/nfs-check
" || {
	echo 'FAILURE: marker missing on NFS'
	exit 1
}

MW_CTR=$(docker exec "${NEW_NODE}" docker ps \
	--filter "name=${STACK_NAME}_mediawiki" \
	--format '{{.ID}}' | head -1)
if [ -z "${MW_CTR}" ]; then
	echo "FAILURE: cannot locate MediaWiki container on ${NEW_NODE}"
	exit 1
fi
for i in $(seq 1 30); do
	if docker exec "${NEW_NODE}" docker exec "${MW_CTR}" \
		curl -fsS http://localhost:80/ >/dev/null 2>&1; then
		echo "MediaWiki reachable after reschedule"
		exit 0
	fi
	sleep 2
done
echo "FAILURE: MediaWiki not reachable after reschedule"
exit 1
