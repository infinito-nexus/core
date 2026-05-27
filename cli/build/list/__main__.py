#!/usr/bin/env python3
"""
Generate a JSON file listing all Ansible role directories.

Usage:
  python -m cli.build.list [--roles-dir path/to/roles] [--output path/to/roles/list.json | console]
"""
import os
import json
import argparse

from . import PROJECT_ROOT


def find_roles(roles_dir: str):
    """Return sorted list of role names under roles_dir."""
    return sorted([
        entry for entry in os.listdir(roles_dir)
        if os.path.isdir(os.path.join(roles_dir, entry))
    ])


def write_roles_list(roles, out_file):
    """Write the list of roles to out_file as JSON."""
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(roles, f, indent=2)
    print(f"Wrote roles list to {out_file}")


def main():
    default_roles_dir = str(PROJECT_ROOT / "roles")
    default_output = os.path.join(default_roles_dir, 'list.json')

    parser = argparse.ArgumentParser(description='Generate roles/list.json')
    parser.add_argument(
        '--roles-dir', '-r',
        default=default_roles_dir,
        help=f'Directory containing role subfolders (default: {default_roles_dir})'
    )
    parser.add_argument(
        '--output', '-o',
        default=default_output,
        help=(
            'Output path for roles list JSON ' 
            '(or "console" to print to stdout, default: %(default)s)'
        )
    )
    args = parser.parse_args()

    if not os.path.isdir(args.roles_dir):
        parser.error(f"Roles directory not found: {args.roles_dir}")

    roles = find_roles(args.roles_dir)

    if args.output.lower() == 'console':
        # Print JSON to stdout
        print(json.dumps(roles, indent=2))
    else:
        write_roles_list(roles, args.output)

if __name__ == '__main__':
    main()
