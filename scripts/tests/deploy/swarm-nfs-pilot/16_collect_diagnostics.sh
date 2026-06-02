#!/usr/bin/env bash
set +e

sep() {
	echo "=========================================="
	echo "=== $1"
	echo "=========================================="
}

for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	sep "${node}: /opt/compose tree"
	docker exec "${node}" find /opt/compose -maxdepth 3 -type f -name '*.yml' 2>/dev/null
	for f in $(docker exec "${node}" sh -c \
		'find /opt/compose -maxdepth 3 -type f -name "compose*.yml" 2>/dev/null'); do
		sep "${node}:${f}"
		docker exec "${node}" cat -n "${f}" 2>/dev/null
	done
done

sep "swarm nodes"
docker exec "${MGR}" docker node ls

sep "all swarm services + replica state"
docker exec "${MGR}" docker service ls

sep "per-service docker service ps (--no-trunc) for every existing service"
for svc in $(docker exec "${MGR}" docker service ls --format '{{.Name}}'); do
	echo "--- ${svc} ---"
	docker exec "${MGR}" docker service ps --no-trunc "${svc}"
	echo "--- ${svc} logs (tail 50) ---"
	docker exec "${MGR}" docker service logs --tail 50 "${svc}" 2>&1 | head -100
done

sep "docker images per node (filter custom + mariadb + mediawiki)"
for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	echo "--- ${node} ---"
	docker exec "${node}" docker images | grep -E 'mariadb|mediawiki|custom' || echo "(none)"
done

sep "rendered env files on manager (value lengths only)"
docker exec "${MGR}" sh -c 'for f in /opt/compose/*/\.env/env /opt/compose/*/.env/env; do
  [ -f "$f" ] || continue
  echo "--- $f ---"
  awk -F= '"'"'{ if (NF>=2) { v=substr($0, index($0, "=")+1); printf "%s=<%d-char value>\n", $1, length(v) } else { print $0 } }'"'"' "$f"
done'

sep "live mariadb task container env (MARIADB* only, value prefix redacted)"
MARIADB_CID=$(docker exec "${MGR}" sh -c \
	'docker ps --filter label=com.docker.swarm.service.name=mariadb_mariadb --format "{{.ID}}" | head -n1')
if [ -n "${MARIADB_CID}" ]; then
	docker exec "${MGR}" docker exec "${MARIADB_CID}" sh -c \
		'env | grep -E "^MARIADB|^MYSQL" | sed "s/=\(.\{1,3\}\).*/=\1...(redacted)/"' ||
		echo "(failed to exec into ${MARIADB_CID})"
else
	echo "(no live mariadb task container found)"
fi

sep "nfs-server logs"
docker logs --tail 200 "${NFS_SERVER}"

for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	echo "=== ${node} volumes ==="
	docker exec "${node}" docker volume ls
	echo "=== ${node} mount points (nfs filter) ==="
	docker exec "${node}" mount | grep -i nfs
done
