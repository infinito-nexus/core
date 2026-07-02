#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_context.sh"
set +e
set +o pipefail
set +u

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
	echo "--- ${svc} logs (full) ---"
	docker exec "${MGR}" docker service logs "${svc}" 2>&1
done

sep "docker images per node (filter custom + db + ${ENTITY})"
for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	echo "--- ${node} ---"
	docker exec "${node}" docker images | grep -E "mariadb|postgres|${ENTITY}|custom" || echo "(none)"
done

sep "rendered env files on manager (value lengths only)"
docker exec "${MGR}" sh -c 'for f in /opt/compose/*/\.env/env /opt/compose/*/.env/env; do
  [ -f "$f" ] || continue
  echo "--- $f ---"
  awk -F= '"'"'{ if (NF>=2) { v=substr($0, index($0, "=")+1); printf "%s=<%d-char value>\n", $1, length(v) } else { print $0 } }'"'"' "$f"
done'

if [ "${DB_DEP}" = "mariadb" ]; then
	sep "live mariadb container env (MARIADB* only, value prefix redacted)"
	MARIADB_CID=$(docker exec "${MGR}" sh -c \
		'docker ps --filter name=mariadb --format "{{.ID}}" | head -n1')
	if [ -n "${MARIADB_CID}" ]; then
		docker exec "${MGR}" docker exec "${MARIADB_CID}" sh -c \
			'env | grep -E "^MARIADB|^MYSQL" | sed "s/=\(.\{1,3\}\).*/=\1...(redacted)/"' ||
			echo "(failed to exec into ${MARIADB_CID})"
	else
		echo "(no live mariadb container found)"
	fi
fi

sep "nfs-server logs"
docker logs --tail 200 "${NFS_SERVER}"

sep "nfs-server: /etc/exports + exportfs -v + export tree + ganesha conf"
docker exec "${NFS_SERVER}" cat /etc/exports
docker exec "${NFS_SERVER}" exportfs -v
docker exec "${NFS_SERVER}" cat /etc/ganesha/ganesha.conf
docker exec "${NFS_SERVER}" ls -la "${NFS_EXPORT_BASE:-/srv/nfs}"
docker exec "${NFS_SERVER}" ls -la "${NFS_STATE_PATH:-/srv/nfs/infinito-state}"
docker exec "${NFS_SERVER}" systemctl --no-pager --full status nfs-server nfs-ganesha 2>&1 | head -60

sep "nfs-server: kernel nfsd mount boundary + v4 pseudo-root (pins whether the self-bind + cross took)"
docker exec "${NFS_SERVER}" findmnt -R "${NFS_EXPORT_BASE:-/srv/nfs}" 2>&1
docker exec "${NFS_SERVER}" mountpoint "${NFS_STATE_PATH:-/srv/nfs/infinito-state}" 2>&1
docker exec "${NFS_SERVER}" cat /proc/fs/nfsd/exports 2>&1
docker exec "${NFS_SERVER}" cat /proc/fs/nfsd/versions 2>&1
docker exec "${NFS_SERVER}" sh -c "journalctl -u nfs-server -u nfs-ganesha --no-pager 2>&1 | tail -50"

sep "controller (this runner): NFS reachability of nfs-server"
_nfs_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "${NFS_SERVER}")"
echo "nfs-server container IP(s): ${_nfs_ip}"
ip -4 addr show | grep -E "192\.168\.244\." || echo "(controller has no 192.168.244.0/24 address)"
mount | grep -i nfs || echo "(no nfs mounts on controller)"
for _ip in ${_nfs_ip}; do
	echo "--- showmount -e ${_ip} ---"
	showmount -e "${_ip}" 2>&1 || echo "(showmount -e ${_ip} failed; NFSv4-only servers do not answer MOUNT)"
done

for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	echo "=== ${node} volumes ==="
	docker exec "${node}" docker volume ls
	echo "=== ${node} mount points (nfs filter) ==="
	docker exec "${node}" mount | grep -i nfs
done

exit 0
