#!/usr/bin/env python3
"""
Script to ensure each Ansible role under ../roles/ with a given prefix has a vars/main.yml
containing the correct application_id. Can preview actions or overwrite mismatches.
"""

import argparse
import sys
import yaml

from utils.cache.yaml import dump_yaml, load_yaml_any
from pathlib import Path

# Directory containing roles; can be overridden by tests
MODULE_DIR = Path(__file__).resolve().parent
ROLES_DIR = (MODULE_DIR.parents[3] / "roles").resolve()


def process_role(role_dir: Path, prefix: str, preview: bool, overwrite: bool):
    name = role_dir.name
    if not name.startswith(prefix):
        return
    # Expected application_id is role name minus prefix
    expected_id = name[len(prefix) :]
    vars_dir = role_dir / "vars"
    vars_file = vars_dir / "main.yml"
    if vars_file.exists():
        # Load existing variables (cached parse).
        try:
            existing = load_yaml_any(str(vars_file), default_if_missing={}) or {}
        except yaml.YAMLError as e:
            print(f"Error parsing YAML in {vars_file}: {e}", file=sys.stderr)
            return
        if not isinstance(existing, dict):
            print(
                f"Error parsing YAML in {vars_file}: expected mapping at root",
                file=sys.stderr,
            )
            return
        actual_id = existing.get("application_id")
        if actual_id == expected_id:
            # Already correct
            return
        if overwrite:
            # Update only application_id
            existing["application_id"] = expected_id
            if preview:
                print(
                    f"[PREVIEW] Would update {vars_file}: application_id -> {expected_id}"
                )
            else:
                dump_yaml(vars_file, existing)
                print(f"Updated {vars_file}: application_id -> {expected_id}")
        else:
            print(
                f"Mismatch in {vars_file}: application_id='{actual_id}', expected='{expected_id}'"
            )
    else:
        # Create new vars/main.yml
        if preview:
            print(
                f"[PREVIEW] Would create {vars_file} with application_id: {expected_id}"
            )
        else:
            vars_dir.mkdir(parents=True, exist_ok=True)
            dump_yaml(vars_file, {"application_id": expected_id})
            print(f"Created {vars_file} with application_id: {expected_id}")


def run(prefix: str, preview: bool = False, overwrite: bool = False):
    """
    Ensure vars/main.yml for roles under ROLES_DIR with the given prefix has correct application_id.
    """
    for role in sorted(Path(ROLES_DIR).iterdir()):
        if role.is_dir():
            process_role(role, prefix, preview, overwrite)


def main():
    parser = argparse.ArgumentParser(
        description="Ensure vars/main.yml for roles with a given prefix has correct application_id"
    )
    parser.add_argument(
        "--prefix",
        required=True,
        help="Role name prefix to filter (e.g. 'web-', 'svc-', 'desk-')",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="If vars/main.yml exists but application_id mismatches, overwrite only that key",
    )
    args = parser.parse_args()

    # Run processing
    run(prefix=args.prefix, preview=args.preview, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
