import functools
import glob
import os
from pathlib import Path

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


@functools.cache
def _app_id_role_paths(base_dir: str) -> dict[str, tuple[tuple[str, str], ...]]:
    mapping: dict[str, list[tuple[str, str]]] = {}
    pattern = str(Path(base_dir) / "roles" / "*" / ROLE_FILE_VARS_MAIN)
    for filepath in glob.glob(pattern):
        try:
            data = load_yaml_any(filepath, default_if_missing={}) or {}
        except Exception:  # noqa: S112  best-effort iteration over role files; skip malformed input
            continue
        if not isinstance(data, dict):
            continue
        application_id = data.get("application_id")
        if application_id is None:
            continue
        role_dir = str(Path(filepath).parent.parent)
        abs_path = str(Path(role_dir).resolve())
        rel_path = os.path.relpath(role_dir, base_dir)
        mapping.setdefault(application_id, []).append((abs_path, rel_path))
    return {app_id: tuple(paths) for app_id, paths in mapping.items()}


def _role_path_by_application_id(application_id, index):
    matches = _app_id_role_paths(str(Path.cwd())).get(application_id, ())
    if len(matches) > 1:
        raise AnsibleFilterError(
            f"Multiple roles found with application_id='{application_id}': "
            f"{[m[0] for m in matches]}. The application_id must be unique."
        )
    if not matches:
        raise AnsibleFilterError(
            f"No role found with application_id='{application_id}'."
        )
    return matches[0][index]


def abs_role_path_by_application_id(application_id):
    """
    Searches all roles/*/vars/main.yml for application_id and returns
    the absolute path of the role that matches. Raises an error if
    zero or more than one match is found.
    """
    return _role_path_by_application_id(application_id, 0)


def rel_role_path_by_application_id(application_id):
    """
    Searches all roles/*/vars/main.yml for application_id and returns
    the relative path (from the project root) of the role that matches.
    Raises an error if zero or more than one match is found.
    """
    return _role_path_by_application_id(application_id, 1)


class FilterModule:
    """
    Provides the filters `abs_role_path_by_application_id` and
    `rel_role_path_by_application_id`.
    """

    def filters(self):
        return {
            "abs_role_path_by_application_id": abs_role_path_by_application_id,
            "rel_role_path_by_application_id": rel_role_path_by_application_id,
        }
