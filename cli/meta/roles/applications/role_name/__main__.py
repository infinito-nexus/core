#!/usr/bin/env python3
"""
CLI Script: get_role_folder_cli.py

This script determines the appropriate Ansible role folder based on the provided application_id
by inspecting each role's vars/main.yml within the roles directory. By default, it assumes the
roles directory is located at the project root, relative to this script's location.

"""

import argparse
import os
import sys
from pathlib import Path

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT


def get_role(application_id, roles_path):
    """
    Find the role directory under `roles_path` whose vars/main.yml contains the specified application_id.

    :param application_id: The application_id to match.
    :param roles_path: Path to the roles directory.
    :return: The name of the matching role directory.
    :raises RuntimeError: If no match is found or if an error occurs while reading files.
    """
    if not Path(roles_path).is_dir():
        raise RuntimeError(f"Roles path not found: {roles_path}")

    for role in sorted(os.listdir(roles_path)):
        role_dir = str(Path(roles_path) / role)
        vars_file = str(Path(role_dir) / ROLE_FILE_VARS_MAIN)
        if Path(vars_file).is_file():
            try:
                data = load_yaml(vars_file)
            except Exception as e:
                raise RuntimeError(f"Failed to load {vars_file}: {e}") from e

            if data.get("application_id") == application_id:
                return role

    raise RuntimeError(
        f"No role found with application_id '{application_id}' in {roles_path}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Determine the Ansible role folder by application_id"
    )
    parser.add_argument(
        "application_id",
        help="The application_id defined in vars/main.yml to search for",
    )
    parser.add_argument(
        "-r",
        "--roles-path",
        default=str(PROJECT_ROOT / "roles"),
        help="Path to the roles directory (default: roles/ at project root)",
    )

    args = parser.parse_args()

    try:
        folder = get_role(args.application_id, args.roles_path)
        print(folder)
        sys.exit(0)
    except RuntimeError as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
