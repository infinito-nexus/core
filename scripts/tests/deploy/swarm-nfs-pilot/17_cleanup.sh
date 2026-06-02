#!/usr/bin/env bash
set +e

docker rm -f "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}"
docker network rm swarm-lab
exit 0
