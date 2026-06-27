#!/usr/bin/env bash
# Reclaim ALL leftover act-swarm state (DinD nodes, NFS sidecars, lab networks,
# act outer containers) from aborted or wedged roundtrip swarm runs, across every
# cluster id. Unlike 13_cleanup.sh (one cluster via SWARM_NAME), this nukes every
# act-swarm container/network so the next swarm step starts from a clean host.
# Run BETWEEN swarm runs: it would kill an in-flight one.
#
# Scope is precise, never by guessed name prefix, so unrelated containers (a
# production `nfs-server`, someone's own `swarm-mgr`, ...) are NEVER touched:
#   - DinD nodes + NFS sidecars carry the INFINITO_SWARM_TEST_LABEL label (SPOT in
#     default.env, stamped by 01_start_nfs.sh / 02_start_swarm_nodes.sh).
#   - the act outer container is matched by act's own job-name prefix.
#   - lab networks are matched by the `swarm-lab` token the harness assigns.
# Containers created before the label existed are not matched; those are wedged
# D-state remnants that a host `systemctl restart docker` clears anyway.
#
# Two layers:
#   1. docker (no privileges): rm matching containers + lab networks + prune.
#   2. host (root): D-state containers (wedged kernel NFS, "did not receive an
#      exit event") survive `docker rm -f`; clear with umount + exportfs + a docker
#      restart. Attempted with passwordless sudo, reported under a no-priv sandbox.
set -uo pipefail

# INFINITO_SWARM_TEST_LABEL lives in the env SPOT (default.env -> .env).
# shellcheck source=scripts/meta/env/load.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)/scripts/meta/env/load.sh"

_act_name='act--Test-Deploy-swarm'

_select_ids() {
	docker ps -aq --filter "label=${INFINITO_SWARM_TEST_LABEL}" 2>/dev/null
	docker ps -aq --filter "name=${_act_name}" 2>/dev/null
}
_select_names() {
	docker ps -a --format '{{.Names}}' --filter "label=${INFINITO_SWARM_TEST_LABEL}" 2>/dev/null
	docker ps -a --format '{{.Names}}' --filter "name=${_act_name}" 2>/dev/null
}

echo ">>> act-swarm-clean: leftover containers"
_ctrs="$(_select_ids | sort -u)"
if [ -n "${_ctrs}" ]; then
	# shellcheck disable=SC2086  # intentional word-split of the id list
	docker rm -f ${_ctrs} 2>&1 | sed 's/^/    /' || true
fi

echo ">>> act-swarm-clean: leftover networks"
_nets="$(docker network ls --format '{{.Name}}' | grep -E "${INFINITO_SWARM_LAB_NET_NAME}" || true)"
if [ -n "${_nets}" ]; then
	# shellcheck disable=SC2086  # intentional word-split of the network list
	docker network rm ${_nets} 2>&1 | sed 's/^/    /' || true
fi
docker network prune -f >/dev/null 2>&1 || true

_left="$(_select_names | sort -u)"
if [ -z "${_left}" ]; then
	echo ">>> act-swarm-clean: done, no remnants"
	exit 0
fi

echo ">>> act-swarm-clean: D-state remnants survived docker rm -f:"
echo "    ${_left//$'\n'/$'\n'    }"
if sudo -n true 2>/dev/null; then
	echo ">>> clearing wedged kernel NFS on host (sudo)"
	sudo umount -f -l "${INFINITO_DIR_VAR_LIB:?}" 2>/dev/null || true
	sudo exportfs -ua 2>/dev/null || true
	sudo systemctl restart docker
	echo ">>> docker restarted; D-state remnants cleared"
else
	echo "!!! sudo unavailable here (sandbox). Clear on the host:"
	echo "    sudo umount -f -l ${INFINITO_DIR_VAR_LIB}; sudo exportfs -ua; sudo systemctl restart docker"
	exit 1
fi
