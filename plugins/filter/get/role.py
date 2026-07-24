"""
Ansible filter plugin: get_role

This filter inspects each role under the given roles directory, loads its vars/main.yml,
and returns the role folder name whose application_id matches the provided value.
"""

import os
from pathlib import Path

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


def get_role(application_id, roles_path="roles"):
    """
    Find the role directory under `roles_path` whose vars/main.yml contains the given application_id.

    :param application_id: The application_id to match.
    :param roles_path: Path to the roles directory (default: 'roles').
    :return: The name of the matching role directory.
    :raises AnsibleFilterError: If vars file is unreadable or no match is found.
    """
    if not Path(roles_path).is_dir():
        raise AnsibleFilterError(f"Roles path not found: {roles_path}")

    for role in os.listdir(roles_path):
        role_dir = str(Path(roles_path) / role)
        vars_file = str(Path(role_dir) / ROLE_FILE_VARS_MAIN)
        if Path(vars_file).is_file():
            try:
                data = load_yaml_any(vars_file, default_if_missing={}) or {}
            except Exception as e:
                raise AnsibleFilterError(f"Failed to load {vars_file}: {e}") from e
            if not isinstance(data, dict):
                continue

            if data.get("application_id") == application_id:
                return role

    raise AnsibleFilterError(
        f"No role found with application_id '{application_id}' in {roles_path}"
    )


class FilterModule:
    """
    Register the get_role filter
    """

    def filters(self):
        return {
            "get_role": get_role,
        }
