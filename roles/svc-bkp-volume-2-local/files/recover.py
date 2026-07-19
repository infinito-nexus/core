#!/usr/bin/env python3
"""Restore a docker volume's files from a backup-docker-to-local
generation.

Runs the role's deployed backup unit first (the usual baudolo run,
storing a fresh differential generation of every volume and database),
resolves the volume's mountpoint and mirrors the snapshot into it
(``rsync -a --delete``). Stop the consuming project first. Database
restores stay with ``baudolo-restore postgres|mariadb``.

Host-agnostic: with ``--docker-host ssh://user@host`` the volume is
inspected on that host and the snapshot is rsync-pushed onto its
mountpoint over ssh, recovering a volume on a remote machine.

Usage:
    recover.py SOURCE_DIR VOLUME [--no-safety-backup] [--docker-host ENDPOINT]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]  # nocheck: project-root-import
sys.path.insert(0, str(_REPO_ROOT))

from utils.recovery.base import DirectoryRecovery  # noqa: E402


class VolumeRecovery(DirectoryRecovery):
    unit_pattern = "svc-bkp-volume-2-local*.service"

    def __init__(
        self,
        source_dir: str,
        volume: str,
        *,
        service_backup: bool = True,
        docker_host: str | None = None,
    ) -> None:
        docker = ["docker", *(["-H", docker_host] if docker_host else [])]
        mountpoint = subprocess.run(
            [*docker, "volume", "inspect", "--format", "{{.Mountpoint}}", volume],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        target = (
            f"{docker_host.split('://', 1)[-1]}:{mountpoint}"
            if docker_host
            else mountpoint
        )
        super().__init__(source_dir, target, service_backup=service_backup)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source_dir",
        help="snapshot to restore from (e.g. <backups>/<machine-hash>/backup-docker-to-local/<generation>/<volume>/files)",
    )
    parser.add_argument("volume", help="docker volume name to restore into")
    parser.add_argument(
        "--no-safety-backup",
        action="store_true",
        help="skip the pre-recover safety backup of the current target (only when it holds nothing worth saving)",
    )
    parser.add_argument(
        "--docker-host",
        help="remote docker endpoint (e.g. ssh://user@host) to recover the volume on another host",
    )
    args = parser.parse_args()
    return VolumeRecovery(
        args.source_dir,
        args.volume,
        service_backup=not args.no_safety_backup,
        docker_host=args.docker_host,
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
