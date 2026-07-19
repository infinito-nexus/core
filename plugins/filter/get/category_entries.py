# Custom Ansible filter to get all role names under "roles/" with a given prefix.

import os
from pathlib import Path


def get_category_entries(prefix, roles_path="roles"):
    """
    Returns a list of role names under the given roles_path
    that start with the specified prefix.

    :param prefix: String prefix to match role names.
    :param roles_path: Path to the roles directory (default: 'roles').
    :return: List of matching role names.
    """
    if not Path(roles_path).is_dir():
        return []

    roles = []
    for entry in os.listdir(roles_path):
        full_path = str(Path(roles_path) / entry)
        if Path(full_path).is_dir() and entry.startswith(prefix):
            roles.append(entry)

    return sorted(roles)


class FilterModule:
    """Custom filters for Ansible"""

    def filters(self):
        return {"get_category_entries": get_category_entries}
