#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_context.sh"

export APP_ID DB_DEP

python3 - <<'PY'
import os
from pathlib import Path

from utils.cache.yaml import dump_yaml, load_yaml_any

INV_PATH = Path("/tmp/inv/devices.yml")  # noqa: S108
APP_ID = os.environ["APP_ID"]
DB_DEP = os.environ["DB_DEP"]

DOCKER_VARS = {
    "ansible_connection": "docker",
    "ansible_python_interpreter": "/usr/bin/python3",
    "ansible_user": "root",
}

GROUP_HOSTS = [
    ("svc-docker-swarm", "swarm-mgr-01"),
    ("svc-docker-swarm", "swarm-wrk-01"),
    ("svc-docker-swarm", "swarm-wrk-02"),
    ("svc-docker-swarm-manager", "swarm-mgr-01"),
    ("svc-storage-nfs-client", "swarm-mgr-01"),
    ("svc-storage-nfs-client", "swarm-wrk-01"),
    ("svc-storage-nfs-client", "swarm-wrk-02"),
    ("svc-storage-nfs-server", "nfs-server"),
    ("svc-docker-registry", "swarm-mgr-01"),
    (APP_ID, "swarm-mgr-01"),
]
if DB_DEP == "mariadb":
    GROUP_HOSTS.append(("svc-db-mariadb", "swarm-mgr-01"))
elif DB_DEP == "postgres":
    GROUP_HOSTS.append(("svc-db-postgres", "swarm-mgr-01"))

inv = load_yaml_any(str(INV_PATH), default_if_missing={})
inv.setdefault("all", {}).setdefault("children", {})
children = inv["all"]["children"]

for group, host in GROUP_HOSTS:
    children.setdefault(group, {}).setdefault("hosts", {})
    children[group]["hosts"][host] = DOCKER_VARS

dump_yaml(str(INV_PATH), inv)
print(INV_PATH.read_text())
PY
