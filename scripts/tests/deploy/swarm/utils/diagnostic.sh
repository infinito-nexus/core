#!/usr/bin/env bash
# Backup/NFS diagnostics for a live swarm-test cluster. Runs read-only
# probes inside each node via exec/node.sh: backup unit state + recent
# journal, NFS mounts, D-state (wedged kernel-NFS) processes, rsync/dump
# processes, and disk usage. Use after a swarm-zombie run to root-cause a
# hung backup unit without hand-writing docker exec pipelines.
#
# Env:
#   SWARM_NAME   cluster id (the app id when no name= was passed)
#   node         optional single node container name; default: probe
#                mgr-01, nfs-server and bkp-01
#   unit         optional systemd unit glob for the journal dump;
#                default: svc-bkp-*
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXEC_NODE="${SCRIPT_DIR}/../../act/exec/node.sh"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
DIR_VAR_LIB="$(PYTHONPATH="${REPO_ROOT}" python3 -c 'from utils.paths import DIR_VAR_LIB; print(DIR_VAR_LIB)')"

CLUSTER="${SWARM_NAME:?SWARM_NAME=<cluster-id> required}"
UNIT_GLOB="${unit:-svc-bkp-*}"

if [[ -n "${node:-}" ]]; then
	NODES=("${node}")
else
	NODES=(
		"${CLUSTER}-swarm-mgr-01"
		"${CLUSTER}-nfs-server"
		"${CLUSTER}-swarm-bkp-01"
	)
fi

read -r -d '' PROBE <<PROBE_EOF || true
echo "### backup units"
systemctl list-units --type=service --all --no-legend '${UNIT_GLOB}' 2>/dev/null | awk '{print \$1, \$3, \$4}'
echo "### backup unit journals (last 60 lines each)"
for u in \$(systemctl list-units --type=service --all --no-legend '${UNIT_GLOB}' 2>/dev/null | awk '{print \$1}'); do
  echo "--- \$u ---"
  journalctl -u "\$u" --no-pager -n 60 2>/dev/null | tail -60
done
echo "### NFS mounts"
mount 2>/dev/null | grep -iE 'nfs|${DIR_VAR_LIB}' || echo '(none)'
echo "### D-state processes (uninterruptible; often a wedged NFS mount)"
ps -eo stat,pid,comm,args 2>/dev/null | awk '\$1 ~ /^D/' || true
echo "### rsync / baudolo / db-dump processes"
ps -eo pid,etime,stat,args 2>/dev/null | grep -iE 'rsync|baudolo|mariadb-dump|pg_dump' | grep -v grep || echo '(none)'
echo "### disk"
df -h '${DIR_VAR_LIB}' 2>/dev/null || df -h /
PROBE_EOF

B64="$(printf '%s' "${PROBE}" | base64 | tr -d '\n')"

for n in "${NODES[@]}"; do
	echo "================================================================"
	echo "== NODE: ${n}"
	echo "================================================================"
	node="${n}" cmd="echo ${B64} | base64 -d | bash" bash "${EXEC_NODE}" 2>&1 ||
		echo "(node ${n} unreachable or wedged)"
done
