#!/usr/bin/env python3

import glob
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


def get_all_application_ids(roles_dir="roles"):
    """
    Ansible filter to retrieve all unique application_id values
    defined in roles/*/vars/main.yml files.

    :param roles_dir: Base directory for Ansible roles (default: 'roles')
    :return: Sorted list of unique application_id strings
    """
    pattern = str(Path(roles_dir) / "*" / ROLE_FILE_VARS_MAIN)
    app_ids = []

    for filepath in glob.glob(pattern):
        try:
            data = load_yaml_any(filepath, default_if_missing={})
        except Exception:  # noqa: S112  best-effort iteration over role files; skip malformed input
            continue

        if isinstance(data, dict) and "application_id" in data:
            app_ids.append(data["application_id"])

    return sorted(set(app_ids))


class FilterModule:
    """
    Ansible filter plugin for retrieving application IDs.
    """

    def filters(self):
        return {"get_all_application_ids": get_all_application_ids}
