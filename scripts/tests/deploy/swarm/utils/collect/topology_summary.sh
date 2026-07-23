#!/usr/bin/env bash
# Renders the swarm lab structure into GITHUB_STEP_SUMMARY: the topology
# SPOT roles (manager, workers, NFS, backup) plus the live node list and
# service placement read from the manager. Inputs via env (topology
# export.sh): SWARM_NAME MGR WRK1 WRK2 NFS_SERVER BACKUP_NODE
# SWARM_LAB_NETWORK GITHUB_STEP_SUMMARY.
set -euo pipefail

: "${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY must be set}"
: "${MGR:?topology export.sh must run first}"

dexec() {
	timeout 30 docker exec "$@" 2>&1 || echo "(unreachable)"
}

{
	echo "## 🕸️ Swarm structure — ${SWARM_NAME:-unknown}"
	echo
	echo "| Role | Host |"
	echo "|---|---|"
	echo "| manager | \`${MGR}\` |"
	echo "| worker 1 | \`${WRK1}\` |"
	echo "| worker 2 | \`${WRK2}\` |"
	echo "| NFS server | \`${NFS_SERVER}\` |"
	echo "| backup node | \`${BACKUP_NODE}\` |"
	echo "| lab network | \`${SWARM_LAB_NETWORK}\` |"
	echo
	echo "### Nodes"
	echo
	echo '```'
	dexec "${MGR}" docker node ls
	echo '```'
	echo
	echo "### Service placement"
	echo
	echo '```'
	# shellcheck disable=SC2016  # $(...) must expand inside the manager, not here
	dexec "${MGR}" sh -c \
		'docker service ps $(docker service ls -q) --format "table {{.Name}}\t{{.Node}}\t{{.CurrentState}}" 2>/dev/null | sort -u'
	echo '```'
} >>"${GITHUB_STEP_SUMMARY}"
