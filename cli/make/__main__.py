#!/usr/bin/env python3
"""
CLI wrapper for Makefile targets within Infinito.Nexus.
Invokes `make` commands in the project root directory.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        prog="infinito make",
        description="Run Makefile targets for Infinito.Nexus project",
    )
    parser.add_argument(
        "targets",
        nargs=argparse.REMAINDER,
        help="Make targets and options to pass to `make`",
    )
    args = parser.parse_args()

    # Default to 'build' if no target is specified
    make_args = args.targets or ["build"]

    from . import PROJECT_ROOT

    repo_root = str(PROJECT_ROOT)

    # Check for Makefile
    makefile_path = str(Path(repo_root) / "Makefile")
    if not Path(makefile_path).is_file():
        print(f"Error: Makefile not found in {repo_root}", file=sys.stderr)
        sys.exit(1)

    # Invoke make in repo root
    cmd = ["make", *make_args]
    try:
        result = subprocess.run(cmd, cwd=repo_root, check=False)
        sys.exit(result.returncode)
    except FileNotFoundError:
        print("Error: 'make' command not found. Please install make.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
