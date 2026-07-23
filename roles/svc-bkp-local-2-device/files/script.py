#!/usr/bin/env python3

import datetime
import glob
import os
import subprocess
import sys
from pathlib import Path


def main():
    source_path = sys.argv[1]
    print(f"source path: {source_path}")

    backup_to_usb_destination_path = sys.argv[2]
    print(f"backup to usb destination path: {backup_to_usb_destination_path}")

    if not Path(backup_to_usb_destination_path).is_dir():
        print(f"Directory {backup_to_usb_destination_path} does not exist")
        sys.exit(1)

    machine_id = subprocess.run(
        ["sha256sum", "/etc/machine-id"], capture_output=True, text=True, check=True
    ).stdout.strip()[:64]
    print(f"machine id: {machine_id}")

    versions_path = str(
        Path(backup_to_usb_destination_path) / f"{machine_id}/svc-bkp-local-2-device/"
    )
    print(f"versions path: {versions_path}")

    if not Path(versions_path).is_dir():
        print(f"Creating {versions_path}...")
        Path(versions_path).mkdir(parents=True, exist_ok=True)

    previous_version_path = max(
        glob.glob(f"{versions_path}*"), key=os.path.getmtime, default=None
    )
    print(f"previous versions path: {previous_version_path}")

    current_version_path = str(
        Path(versions_path)
        / datetime.datetime.now(tz=datetime.UTC).strftime("%Y%m%d%H%M%S")
    )
    print(f"current versions path: {current_version_path}")

    print("Creating backup destination folder...")
    Path(current_version_path).mkdir(parents=True, exist_ok=True)

    print("Starting synchronization...")
    try:
        rsync_command = [
            "rsync",
            "-abP",
            "--numeric-ids",
            "--delete",
            "--delete-excluded",
        ]
        if previous_version_path is not None:
            rsync_command.append("--link-dest=" + previous_version_path)
        rsync_command.extend([source_path, current_version_path])
        rsync_output = subprocess.check_output(
            rsync_command, stderr=subprocess.STDOUT, text=True
        )

        print(rsync_output)
        print("Synchronization finished")
        sys.exit(0)
    except subprocess.CalledProcessError as e:
        print(e.output)
        if (
            "rsync warning: some files vanished before they could be transferred"
            in e.output
        ):
            print("Synchronization finished with rsync warning")
            sys.exit(0)
        else:
            print("Synchronization failed")
            sys.exit(1)


if __name__ == "__main__":
    main()
