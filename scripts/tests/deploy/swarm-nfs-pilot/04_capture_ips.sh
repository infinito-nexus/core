#!/usr/bin/env bash
set -euo pipefail

MGR_IP=$(docker inspect "${MGR}" \
	--format '{{(index .NetworkSettings.Networks "swarm-lab").IPAddress}}')
NFS_IP=$(docker inspect "${NFS_SERVER}" \
	--format '{{(index .NetworkSettings.Networks "swarm-lab").IPAddress}}')

echo "MGR_IP=${MGR_IP}" >>"$GITHUB_ENV"
echo "NFS_IP=${NFS_IP}" >>"$GITHUB_ENV"
