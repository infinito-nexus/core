#!/usr/bin/env bash
# shellcheck disable=SC2034  # variables are consumed by callers that source this file
# Manager-node container name in the simulated swarm.
MGR=swarm-mgr-01

# Base export path on the NFS server that backs swarm-shared volumes.
NFS_EXPORT_BASE=/srv/nfs

# NFS-server container name in the simulated swarm.
NFS_SERVER=nfs-server

# Docker bridge network that links every simulated swarm container.
SWARM_LAB_NETWORK=swarm-lab

# Worker-node-1 container name in the simulated swarm.
WRK1=swarm-wrk-01

# Worker-node-2 container name in the simulated swarm.
WRK2=swarm-wrk-02
