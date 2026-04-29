#!/usr/bin/env python3
"""CLI wrapper around the shared applications in-group dependency resolver."""

from __future__ import annotations

import argparse
import os
import sys

from utils.cache.yaml import dump_yaml_str

from utils.applications.in_group_deps import applications_if_group_and_all_deps
from utils.cache.yaml import load_yaml

__all__ = [
    "find_role_dirs_by_app_id",
    "main",
]


def _project_root() -> str:
    script_dir = os.path.dirname(__file__)
    return os.path.abspath(os.path.join(script_dir, "..", "..", "..", ".."))


def find_role_dirs_by_app_id(app_ids: list[str], roles_dir: str) -> list[str]:
    """
    Map application_ids to role directory names based on vars/main.yml in each role.
    """
    mapping: dict[str, str] = {}
    for role in os.listdir(roles_dir):
        role_path = os.path.join(roles_dir, role)
        vars_file = os.path.join(role_path, "vars", "main.yml")
        if not os.path.isfile(vars_file):
            continue
        try:
            data = load_yaml(vars_file)
        except Exception:
            continue
        app_id = data.get("application_id")
        if isinstance(app_id, str) and app_id:
            mapping[app_id] = role

    dirs: list[str] = []
    for group_id in app_ids:
        if group_id in mapping:
            dirs.append(mapping[group_id])
            continue
        if os.path.isdir(os.path.join(roles_dir, group_id)):
            dirs.append(group_id)
    return dirs


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Filter applications by group names (role dirs or application_ids), "
            "meta dependencies, and shared service dependencies."
        )
    )
    parser.add_argument(
        "-a",
        "--applications",
        type=str,
        required=True,
        help="Path to YAML file defining the applications dict.",
    )
    parser.add_argument(
        "-g",
        "--groups",
        nargs="+",
        required=True,
        help="List of group names to filter by (role directory names or application_ids).",
    )
    args = parser.parse_args()

    try:
        data = load_yaml(args.applications)
    except Exception as exc:
        print(f"Error loading applications file: {exc}", file=sys.stderr)
        return 1

    if (
        isinstance(data, dict)
        and "applications" in data
        and isinstance(data["applications"], dict)
    ):
        applications = data["applications"]
    else:
        applications = data

    if not isinstance(applications, dict):
        print(
            (
                "Expected applications YAML to contain a mapping "
                "(or 'applications' mapping), "
                f"got {type(applications).__name__}"
            ),
            file=sys.stderr,
        )
        return 1

    project_root = _project_root()
    roles_dir = os.path.join(project_root, "roles")

    group_dirs = find_role_dirs_by_app_id(args.groups, roles_dir)
    if not group_dirs:
        print(
            f"No matching role directories found for groups: {args.groups}",
            file=sys.stderr,
        )
        return 1

    try:
        filtered = applications_if_group_and_all_deps(
            applications,
            group_dirs,
            project_root=project_root,
            roles_dir=roles_dir,
        )
    except Exception as exc:
        print(f"Error running resolver: {exc}", file=sys.stderr)
        return 1

    print(dump_yaml_str(filtered))
    return 0


if __name__ == "__main__":
    sys.exit(main())
