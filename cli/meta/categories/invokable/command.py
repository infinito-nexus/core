#!/usr/bin/env python3
"""
CLI for extracting invokable or non-invokable role paths from a nested roles YAML file.

Layout assumption: this module sits under ``cli/`` and reads
``<repo_root>/roles/categories.yml`` plus filter plugins under
``<repo_root>/plugins/filter/``.
"""

from __future__ import annotations

import argparse
import sys

import yaml

# IMPORTANT:
# These imports must exist at module level so unittest.mock.patch()
# can replace them in tests.
from plugins.filter.invokable_paths import (
    get_invokable_paths,
    get_non_invokable_paths,
)

from . import PROJECT_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract invokable or non-invokable role paths from a nested roles YAML file."
    )

    parser.add_argument(
        "roles_file",
        nargs="?",
        default=None,
        help="Path to roles/categories.yml (optional).",
    )

    parser.add_argument(
        "--suffix",
        "-s",
        default=None,
        help="Optional suffix to append to each path.",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--non-invokable",
        "-n",
        action="store_true",
        help="List non-invokable paths.",
    )
    mode.add_argument(
        "--invokable",
        "-i",
        action="store_true",
        help="List invokable paths (default).",
    )

    args = parser.parse_args()

    # Ensure repo root is importable (CLI use outside repo root)
    repo_root = PROJECT_ROOT
    sys.path.insert(0, str(repo_root))

    try:
        if args.non_invokable:
            paths = get_non_invokable_paths(args.roles_file, args.suffix)
        else:
            paths = get_invokable_paths(args.roles_file, args.suffix)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    except yaml.YAMLError as e:
        print(f"Error parsing YAML: {e}", file=sys.stderr)
        sys.exit(1)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
