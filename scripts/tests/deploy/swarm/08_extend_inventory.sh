#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_context.sh"

export APP_ID DB_DEP

python3 - <<'PY'
import os
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.roles.entity_name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

INV_PATH = Path("/tmp/inv/devices.yml")  # noqa: S108
APP_ID = os.environ["APP_ID"]
DB_DEP = os.environ["DB_DEP"]
MANAGER = "swarm-mgr-01"

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
    (APP_ID, "swarm-mgr-01"),
    (APP_ID, "swarm-wrk-01"),
    (APP_ID, "swarm-wrk-02"),
]

# Mirrors the runtime constructor add_host so CLI pre-flight passes too.
for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
    if not role_dir.is_dir():
        continue
    meta = role_dir / ROLE_FILE_META_SERVICES
    if not meta.is_file():
        continue
    data = load_yaml_any(str(meta), default_if_missing={}) or {}
    if not isinstance(data, dict):
        continue
    entity_name = get_entity_name(role_dir.name)
    if not entity_name:
        continue
    entry = data.get(entity_name)
    if not isinstance(entry, dict):
        continue
    if str(entry.get("default_placement", "")) == "manager":
        GROUP_HOSTS.append((role_dir.name, MANAGER))

inv = load_yaml_any(str(INV_PATH), default_if_missing={})
inv.setdefault("all", {}).setdefault("children", {})
children = inv["all"]["children"]

for group, host in GROUP_HOSTS:
    children.setdefault(group, {}).setdefault("hosts", {})
    children[group]["hosts"][host] = DOCKER_VARS

dump_yaml(str(INV_PATH), inv)
print(INV_PATH.read_text())
PY
