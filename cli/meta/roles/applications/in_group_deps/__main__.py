#!/usr/bin/env python3
"""CLI wrapper around the shared applications in-group dependency resolver."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from utils.cache.yaml import dump_yaml_str, load_yaml
from utils.roles.applications.in_group_deps import applications_if_group_and_all_deps
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

__all__ = [
    "find_role_dirs_by_app_id",
    "main",
]


def find_role_dirs_by_app_id(app_ids: list[str], roles_dir: str) -> list[str]:
    """
    Map application_ids to role directory names based on vars/main.yml in each role.
    """
    mapping: dict[str, str] = {}
    for role in os.listdir(roles_dir):
        role_path = str(Path(roles_dir) / role)
        vars_file = str(Path(role_path) / ROLE_FILE_VARS_MAIN)
        if not Path(vars_file).is_file():
            continue
        try:
            data = load_yaml(vars_file)
        except Exception:  # noqa: S112  best-effort iteration over role files; skip malformed input
            continue
        app_id = data.get("application_id")
        if isinstance(app_id, str) and app_id:
            mapping[app_id] = role

    dirs: list[str] = []
    for group_id in app_ids:
        if group_id in mapping:
            dirs.append(mapping[group_id])
            continue
        if Path(str(Path(roles_dir) / group_id)).is_dir():
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

    project_root = str(PROJECT_ROOT)
    roles_dir = str(Path(project_root) / "roles")

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
