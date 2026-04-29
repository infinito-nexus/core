#!/usr/bin/env python3
"""
CLI Script: get_role_folder_cli.py

This script determines the appropriate Ansible role folder based on the provided application_id
by inspecting each role's vars/main.yml within the roles directory. By default, it assumes the
roles directory is located at the project root, relative to this script's location.

"""

import os
import sys
import argparse

from utils.cache.yaml import load_yaml


def get_role(application_id, roles_path):
    """
    Find the role directory under `roles_path` whose vars/main.yml contains the specified application_id.

    :param application_id: The application_id to match.
    :param roles_path: Path to the roles directory.
    :return: The name of the matching role directory.
    :raises RuntimeError: If no match is found or if an error occurs while reading files.
    """
    if not os.path.isdir(roles_path):
        raise RuntimeError(f"Roles path not found: {roles_path}")

    for role in sorted(os.listdir(roles_path)):
        role_dir = os.path.join(roles_path, role)
        vars_file = os.path.join(role_dir, "vars", "main.yml")
        if os.path.isfile(vars_file):
            try:
                data = load_yaml(vars_file)
            except Exception as e:
                raise RuntimeError(f"Failed to load {vars_file}: {e}")

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
        default=os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            os.pardir,
            os.pardir,
            os.pardir,
            "roles",
        ),
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
