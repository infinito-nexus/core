#!/usr/bin/env python3
"""Pull the newest backup generations from a remote provider via rsync.

Every network operation is bounded (ssh ConnectTimeout/ServerAlive, rsync
--timeout): the systemd unit is Type=oneshot and would otherwise inherit the
24h default start timeout, so a stalled provider must fail fast instead of
eating the whole job budget.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SSH_OPTS = (
    "-o BatchMode=yes -o ConnectTimeout=30 "
    "-o ServerAliveInterval=15 -o ServerAliveCountMax=4"
)


def run_command(
    command: str,
    capture_output: bool = True,
    check: bool = True,
    shell: bool = True,
) -> str:
    """
    Run a shell command and return its stdout as a string.

    Default behavior: FAIL (raise) when the command returns a non-zero exit code.
    Use check=False only for optional commands.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=capture_output,
            shell=shell,
            text=True,
            check=check,
        )
        return (result.stdout or "").strip()
    except subprocess.CalledProcessError as e:
        print(f"Command failed (exit {e.returncode}): {command}", file=sys.stderr)
        if e.stdout:
            print(e.stdout, file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        raise


def pull_backups(hostname: str, backups_dir: str) -> None:
    backups_dir = backups_dir.rstrip("/")
    print(f"pulling backups from: {hostname}")

    print("loading meta data...")
    remote_host = f"backup@{hostname}"
    print(f"host address:         {remote_host}")

    remote_machine_id = run_command(
        f'ssh {SSH_OPTS} "{remote_host}" sha256sum /etc/machine-id'
    )[:64]
    print(f"remote machine id:    {remote_machine_id}")

    general_backup_machine_dir = f"{backups_dir}/{remote_machine_id}/"
    print(f"backup root:          {backups_dir}")
    print(f"backup dir:           {general_backup_machine_dir}")

    # Exception: the remote command must byte-match the ssh-wrapper.sh allowlist arm; any drift falls through to its reject echo and corrupts the session.
    remote_backup_types = run_command(
        f'ssh {SSH_OPTS} "{remote_host}" '
        f'"find {general_backup_machine_dir} -maxdepth 1 -type d -execdir basename {{}} ;"'
    ).splitlines()
    print(f"backup types:          {' '.join(remote_backup_types)}")

    for backup_type in remote_backup_types:
        if backup_type == remote_machine_id:
            continue

        print(f"backup type:              {backup_type}")

        general_backup_type_dir = f"{general_backup_machine_dir}{backup_type}/"
        general_versions_dir = general_backup_type_dir

        local_previous_version_dir = ""
        try:
            local_previous_version_dir = run_command(
                f"ls -d {general_versions_dir}* | tail -1",
                check=False,
            )
        except subprocess.CalledProcessError:
            local_previous_version_dir = ""
        print(f"last local backup:      {local_previous_version_dir}")

        remote_backup_versions = run_command(
            f'ssh {SSH_OPTS} "{remote_host}" '
            f'"ls -d {backups_dir}/{remote_machine_id}/{backup_type}/*"'
        ).splitlines()
        print(f"remote backup versions:   {' '.join(remote_backup_versions)}")

        remote_last_backup_dir = (
            remote_backup_versions[-1] if remote_backup_versions else ""
        )
        if not remote_last_backup_dir:
            raise RuntimeError(f"No remote backups found for {hostname}:{backup_type}")

        print(f"last remote backup:       {remote_last_backup_dir}")

        remote_source_path = f"{remote_host}:{remote_last_backup_dir}/"
        print(f"source path:              {remote_source_path}")

        local_backup_destination_path = (
            f"{backups_dir}/{remote_machine_id}/{backup_type}/"
            f"{Path(remote_last_backup_dir).name}"
        )
        print(f"backup destination:       {local_backup_destination_path}")

        print("creating local backup destination folder...")
        Path(local_backup_destination_path).mkdir(parents=True, exist_ok=True)

        rsync_command = (
            f"rsync -abP --numeric-ids --delete --delete-excluded --timeout=300 "
            f'-e "ssh {SSH_OPTS}" '
            f'--rsync-path="sudo rsync" '
            f'--link-dest="{local_previous_version_dir}" '
            f'"{remote_source_path}" "{local_backup_destination_path}"'
        )

        print("starting backup...")
        print(f"executing:                {rsync_command}")

        retry_count = 0
        max_retries = 12
        retry_delay = 300
        last_retry_start = 0
        max_retry_duration = 43200

        rsync_exit_code = 1
        while retry_count < max_retries:
            print(f"Retry attempt: {retry_count + 1}")

            if retry_count > 0:
                current_time = int(time.time())
                last_retry_duration = current_time - last_retry_start
                if last_retry_duration >= max_retry_duration:
                    print(
                        "Last retry took more than 12 hours, increasing max retries to 12."
                    )
                    max_retries = 12

            last_retry_start = int(time.time())
            rsync_exit_code = os.system(rsync_command)  # noqa: S605

            if rsync_exit_code == 0:
                break

            retry_count += 1
            time.sleep(retry_delay)

        if rsync_exit_code != 0:
            raise RuntimeError(
                f"rsync failed after {max_retries} attempts "
                f"for {hostname}:{backup_type}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull backups from a remote backup host via rsync."
    )
    parser.add_argument(
        "hostname",
        help="Hostname from which backup should be pulled",
    )
    parser.add_argument(
        "--folder",
        required=True,
        help="Remote and local backup root directory",
    )
    args = parser.parse_args()

    try:
        pull_backups(args.hostname, args.folder)
        sys.exit(0)
    except Exception as e:
        print(
            f"Backup pull failed for host '{args.hostname}': {e}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
