#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../_context.sh"
set +e
set +o pipefail
set +u

OUT="${INFINITO_RESCUE_DIAGNOSTICS_DIR:?INFINITO_RESCUE_DIAGNOSTICS_DIR is not set - source scripts/meta/env/load.sh first}/${APP_ID}-stack"
if ! mkdir -p "${OUT}" 2>/dev/null || [ ! -w "${OUT}" ]; then
	OUT=""
fi

exec 9>&1
if [ -n "${OUT}" ]; then
	echo "stack diagnostics -> ${OUT}" >&9
else
	echo "stack diagnostics: no writable output dir, falling back to stdout" >&9
fi

# Param: $1 output file slug, $2 section heading
sep() {
	if [ -n "${OUT}" ]; then
		exec >>"${OUT}/$1.txt" 2>&1
	fi
	echo "=========================================="
	echo "=== $2"
	echo "=========================================="
}

dexec() {
	timeout 30 docker exec "$@"
}

for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	sep "compose-tree" "${node}: /opt/compose tree"
	dexec "${node}" find /opt/compose -maxdepth 3 -type f -name '*.yml' 2>/dev/null
	for f in $(dexec "${node}" sh -c \
		'find /opt/compose -maxdepth 3 -type f -name "compose*.yml" 2>/dev/null'); do
		sep "compose-files" "${node}:${f}"
		dexec "${node}" cat -n "${f}" 2>/dev/null
	done
done

sep "images" "docker images per node (filter custom + db + ${ENTITY})"
for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	echo "--- ${node} ---"
	dexec "${node}" docker images | grep -E "mariadb|postgres|${ENTITY}|custom" || echo "(none)"
done

sep "env-lengths" "rendered env files on manager (value lengths only)"
# shellcheck disable=SC2016
dexec "${MGR}" sh -c 'for f in /opt/compose/*/\.env/env /opt/compose/*/.env/env; do
  [ -f "$f" ] || continue
  echo "--- $f ---"
  awk -F= '"'"'{ if (NF>=2) { v=substr($0, index($0, "=")+1); printf "%s=<%d-char value>\n", $1, length(v) } else { print $0 } }'"'"' "$f"
done'

if [ "${DB_DEP}" = "mariadb" ]; then
	sep "mariadb-env" "live mariadb container env (MARIADB* only, value prefix redacted)"
	MARIADB_CID=$(dexec "${MGR}" sh -c \
		'docker ps --filter name=mariadb --format "{{.ID}}" | head -n1')
	if [ -n "${MARIADB_CID}" ]; then
		dexec "${MGR}" docker exec "${MARIADB_CID}" sh -c \
			'env | grep -E "^MARIADB|^MYSQL" | sed "s/=\(.\{1,3\}\).*/=\1...(redacted)/"' ||
			echo "(failed to exec into ${MARIADB_CID})"
	else
		echo "(no live mariadb container found)"
	fi
fi

sep "nfs-exports" "nfs-server: /etc/exports + exportfs -v + export tree + ganesha conf"
dexec "${NFS_SERVER}" cat /etc/exports
dexec "${NFS_SERVER}" exportfs -v
dexec "${NFS_SERVER}" cat /etc/ganesha/ganesha.conf
dexec "${NFS_SERVER}" ls -la "${INFINITO_SWARM_NFS_EXPORT_BASE:?}"
dexec "${NFS_SERVER}" ls -la "${INFINITO_SWARM_NFS_STATE_PATH:?}"
dexec "${NFS_SERVER}" systemctl --no-pager --full status nfs-server nfs-ganesha 2>&1 | head -60

sep "nfs-boundary" "nfs-server: kernel nfsd mount boundary + v4 pseudo-root"
dexec "${NFS_SERVER}" findmnt -R "${INFINITO_SWARM_NFS_EXPORT_BASE:?}" 2>&1
dexec "${NFS_SERVER}" mountpoint "${INFINITO_SWARM_NFS_STATE_PATH:?}" 2>&1
dexec "${NFS_SERVER}" cat /proc/fs/nfsd/exports 2>&1
dexec "${NFS_SERVER}" cat /proc/fs/nfsd/versions 2>&1
dexec "${NFS_SERVER}" sh -c "journalctl -u nfs-server -u nfs-ganesha -u rpcbind --no-pager 2>&1 | tail -50"
dexec "${NFS_SERVER}" sh -c "command -v ss >/dev/null 2>&1 && { ss -lntp | grep -E ':(2049|111)' || echo '(ss ran: nothing listening on 2049/111)'; } || echo '(ss not installed on this node)'"

sep "ganesha-threads" "nfs-server: ganesha thread states (pins where a wedged startup blocks)"
# shellcheck disable=SC2016
dexec "${NFS_SERVER}" sh -c 'pid=$(systemctl show -p MainPID --value nfs-ganesha 2>/dev/null)
[ "${pid:-0}" -gt 0 ] || {
  systemctl show -p ActiveState -p SubState -p NRestarts -p Result nfs-ganesha 2>&1
  exit 0
}
for t in /proc/${pid}/task/*; do
  echo "--- ${t} comm=$(cat ${t}/comm 2>&1) wchan=$(cat ${t}/wchan 2>&1) syscall=$(cat ${t}/syscall 2>&1)"
  grep -E "^State:" ${t}/status 2>&1
  cat ${t}/stack 2>&1
done'

sep "ganesha-userstack" "nfs-server: ganesha userspace backtrace (the kernel stack only says futex; this says whose lock)"
# shellcheck disable=SC2016
dexec "${NFS_SERVER}" sh -c 'pid=$(systemctl show -p MainPID --value nfs-ganesha 2>/dev/null)
[ "${pid:-0}" -gt 0 ] || { echo "(nfs-ganesha reports no main pid)"; exit 0; }
if command -v eu-stack >/dev/null 2>&1; then
  eu-stack -p "${pid}" 2>&1
elif command -v gdb >/dev/null 2>&1; then
  gdb -p "${pid}" -batch -ex "thread apply all bt" 2>&1
else
  echo "(neither eu-stack nor gdb is installed on this node)"
fi'

sep "controller-nfs" "controller (this runner): NFS reachability of nfs-server"
_nfs_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "${NFS_SERVER}")"
echo "nfs-server container IP(s): ${_nfs_ip}"
ip -4 addr show | grep -E "192\.168\.244\." || echo "(controller has no 192.168.244.0/24 address)"
mount | grep -i nfs || echo "(no nfs mounts on controller)"
for _ip in ${_nfs_ip}; do
	echo "--- showmount -e ${_ip} ---"
	timeout 15 showmount -e "${_ip}" 2>&1 || echo "(showmount -e ${_ip} failed; NFSv4-only servers do not answer MOUNT)"
done

sep "volumes-mounts" "volumes and nfs mount points per node"
for node in "${MGR}" "${WRK1}" "${WRK2}"; do
	echo "=== ${node} volumes ==="
	dexec "${node}" docker volume ls
	echo "=== ${node} mount points (nfs filter) ==="
	dexec "${node}" mount | grep -i nfs
done

sep "node-resolver" "per-node name resolution state (a build that cannot resolve dies here)"
for node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}"; do
	echo "=== ${node} ==="
	echo "--- /etc/resolv.conf ---"
	dexec "${node}" cat /etc/resolv.conf
	echo "--- daemon.json ---"
	dexec "${node}" cat /etc/docker/daemon.json
	echo "--- listening udp/tcp sockets ---"
	dexec "${node}" sh -c "ss -lunp 2>/dev/null; ss -lntp 2>/dev/null" || echo "(ss unavailable)"
	echo "--- dnsmasq journal ---"
	dexec "${node}" sh -c "journalctl -u dnsmasq --no-pager 2>&1" || echo "(journalctl unavailable)"
	echo "--- addresses ---"
	dexec "${node}" ip -4 addr show
	echo "--- nat rules ---"
	dexec "${node}" sh -c "iptables-save -t nat 2>/dev/null | head -100" || echo "(iptables-save unavailable)"
	echo "--- resolve probe ---"
	dexec "${node}" sh -c "getent hosts deb.debian.org ghcr.io repo.packagist.org 2>&1" || echo "(getent failed for all three)"
done

sep "node-disk" "per-node disk headroom (the drill sizes images off the pulled tree)"
for node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}"; do
	echo "=== ${node} ==="
	dexec "${node}" df -h
	dexec "${node}" docker system df
done

sep "node-loop" "loop devices (one kernel pool, shared by the runner and every node; cryptsetup and the data roots both draw from it)"
echo "=== runner host ==="
losetup -a
for node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}" "${BACKUP_NODE}"; do
	echo "=== ${node} ==="
	dexec "${node}" sh -c "losetup -a 2>&1" || echo "(losetup unavailable)"
	dexec "${node}" sh -c "ls -l /dev/loop* 2>&1" || echo "(no loop nodes in /dev)"
done

if [ -n "${OUT}" ] && [ "$(find "${OUT}" -type f 2>/dev/null | wc -l)" -eq 0 ]; then
	echo "stack diagnostics: captured no files under ${OUT}" >&9
fi

exit 0
