import glob
import os

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import load_yaml_any


def abs_role_path_by_application_id(application_id):
    """
    Searches all roles/*/vars/main.yml for application_id and returns
    the absolute path of the role that matches. Raises an error if
    zero or more than one match is found.
    """
    base_dir = os.getcwd()
    pattern = os.path.join(base_dir, "roles", "*", "vars", "main.yml")
    matches = []

    for filepath in glob.glob(pattern):
        try:
            data = load_yaml_any(filepath, default_if_missing={}) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        if data.get("application_id") == application_id:
            role_dir = os.path.dirname(os.path.dirname(filepath))
            abs_path = os.path.abspath(role_dir)
            matches.append(abs_path)

    if len(matches) > 1:
        raise AnsibleFilterError(
            f"Multiple roles found with application_id='{application_id}': {matches}. "
            "The application_id must be unique."
        )
    if not matches:
        raise AnsibleFilterError(
            f"No role found with application_id='{application_id}'."
        )

    return matches[0]


def rel_role_path_by_application_id(application_id):
    """
    Searches all roles/*/vars/main.yml for application_id and returns
    the relative path (from the project root) of the role that matches.
    Raises an error if zero or more than one match is found.
    """
    base_dir = os.getcwd()
    pattern = os.path.join(base_dir, "roles", "*", "vars", "main.yml")
    matches = []

    for filepath in glob.glob(pattern):
        try:
            data = load_yaml_any(filepath, default_if_missing={}) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        if data.get("application_id") == application_id:
            role_dir = os.path.dirname(os.path.dirname(filepath))
            rel_path = os.path.relpath(role_dir, base_dir)
            matches.append(rel_path)

    if len(matches) > 1:
        raise AnsibleFilterError(
            f"Multiple roles found with application_id='{application_id}': {matches}. "
            "The application_id must be unique."
        )
    if not matches:
        raise AnsibleFilterError(
            f"No role found with application_id='{application_id}'."
        )

    return matches[0]


class FilterModule(object):
    """
    Provides the filters `abs_role_path_by_application_id` and
    `rel_role_path_by_application_id`.
    """

    def filters(self):
        return {
            "abs_role_path_by_application_id": abs_role_path_by_application_id,
            "rel_role_path_by_application_id": rel_role_path_by_application_id,
        }
