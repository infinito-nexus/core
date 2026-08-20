#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import syslog


def run(cmd: list[str], cwd: str) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def log_kill(action: str, target: str) -> None:
    syslog.openlog(ident="infinito-kill")
    syslog.syslog(syslog.LOG_WARNING, f"sys-ctl-rpr-container-hard: {action} {target}")


def hard_restart_docker_services(dir_path: str) -> None:
    """
    Perform a hard restart of compose services in the given directory
    using compose wrapper (auto env + overrides).
    """
    try:
        abs_dir = os.path.abspath(dir_path)
        project = os.path.basename(abs_dir)

        print(f"Performing hard restart for compose project '{project}' in: {abs_dir}")

        log_kill("compose down + up -d", project)
        run(
            ["compose", "--chdir", abs_dir, "--project", project, "down"],
            cwd=abs_dir,
        )
        run(
            ["compose", "--chdir", abs_dir, "--project", project, "up", "-d"],
            cwd=abs_dir,
        )

        print(f"Hard restart completed successfully in: {abs_dir}")
    except subprocess.CalledProcessError as e:
        print(f"Error during hard restart in {dir_path}: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restart compose services in subdirectories (with compose wrapper)."
    )
    parser.add_argument(
        "parent_directory",
        help="Path to the parent directory containing compose projects",
    )
    parser.add_argument(
        "--only", nargs="+", help="Restart only the specified subdirectories (by name)"
    )
    args = parser.parse_args()

    parent_directory = args.parent_directory

    if not os.path.isdir(parent_directory):
        print(f"Error: {parent_directory} is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    for dir_entry in os.scandir(parent_directory):
        if not dir_entry.is_dir():
            continue

        dir_path = dir_entry.path
        dir_name = os.path.basename(dir_path)
        print(f"Checking directory: {dir_path}")

        compose_file = os.path.join(dir_path, "compose.yml")
        if not os.path.isfile(compose_file):
            print(f"No compose.yml found in {dir_path}. Skipping.")
            continue

        if args.only and dir_name not in args.only:
            print(f"Skipping {dir_name} (not in --only list).")
            continue

        hard_restart_docker_services(dir_path)

    print("Finished hard restart procedure.")


if __name__ == "__main__":
    main()
