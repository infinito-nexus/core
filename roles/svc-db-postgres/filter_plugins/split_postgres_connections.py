import os

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import load_yaml_any


def _iter_role_vars_files(roles_dir):
    if not os.path.isdir(roles_dir):
        raise AnsibleFilterError(f"roles_dir not found: {roles_dir}")
    for name in os.listdir(roles_dir):
        role_path = os.path.join(roles_dir, name)
        if not os.path.isdir(role_path):
            continue
        vars_main = os.path.join(role_path, "vars", "main.yml")
        if os.path.isfile(vars_main):
            yield vars_main


def _is_postgres_role(vars_file):
    try:
        data = load_yaml_any(vars_file, default_if_missing={}) or {}
        if not isinstance(data, dict):
            return False
        # only count roles with explicit database_type: postgres in VARS
        return str(data.get("database_type", "")).strip().lower() == "postgres"
    except Exception:
        # ignore unreadable/broken YAML files quietly
        return False


def split_postgres_connections(total_connections, roles_dir="roles"):
    """
    Return an integer average: total_connections / number_of_roles_with_database_type_postgres.
    Uses max(count, 1) to avoid division-by-zero.
    """
    try:
        total = int(total_connections)
    except Exception:
        raise AnsibleFilterError(
            f"total_connections must be int-like, got: {total_connections!r}"
        )

    count = sum(1 for vf in _iter_role_vars_files(roles_dir) if _is_postgres_role(vf))
    denom = max(count, 1)
    return max(1, total // denom)


class FilterModule(object):
    def filters(self):
        return {"split_postgres_connections": split_postgres_connections}
