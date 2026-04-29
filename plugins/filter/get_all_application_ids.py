#!/usr/bin/env python3
# filter_plugins/get_all_application_ids.py

import glob
import os

from utils.cache.yaml import load_yaml_any


def get_all_application_ids(roles_dir="roles"):
    """
    Ansible filter to retrieve all unique application_id values
    defined in roles/*/vars/main.yml files.

    :param roles_dir: Base directory for Ansible roles (default: 'roles')
    :return: Sorted list of unique application_id strings
    """
    pattern = os.path.join(roles_dir, "*", "vars", "main.yml")
    app_ids = []

    for filepath in glob.glob(pattern):
        try:
            data = load_yaml_any(filepath, default_if_missing={})
        except Exception:
            continue

        if isinstance(data, dict) and "application_id" in data:
            app_ids.append(data["application_id"])

    return sorted(set(app_ids))


class FilterModule(object):
    """
    Ansible filter plugin for retrieving application IDs.
    """

    def filters(self):
        return {"get_all_application_ids": get_all_application_ids}
