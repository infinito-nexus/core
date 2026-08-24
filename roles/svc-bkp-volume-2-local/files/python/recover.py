#!/usr/bin/env python3
# nocheck: mirrored-unit-test - subclasses utils.recovery.base and is exercised
# collectively by tests/unit/python/utils/recovery/test_role_recover_scripts.py; a
# per-role copy would assert the base class twice over
"""Restore a backup-docker-to-local generation: a volume's files, or the
generation's database dumps.

Both modes run the role's deployed backup unit first, unless
``--no-safety-backup`` says the target holds nothing worth saving.

Volume mode mirrors the snapshot into the volume's mountpoint
(``rsync -a --delete``); stop the consuming project first. With
``--docker-host ssh://user@host`` it works on a remote host.

Database mode (``--databases``) replays every dump with
``baudolo-restore --empty`` - a single database through its engine's
subcommand, a ``pg_dumpall`` dump through ``cluster`` - and refuses while a
consumer runs. Local-only: the credentials live in the target's databases.csv.

Usage:
    recover.py SOURCE_DIR VOLUME [--no-safety-backup] [--docker-host ENDPOINT]
    recover.py --databases GENERATION_DIR [--no-safety-backup]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]  # nocheck: project-root-import
sys.path.insert(0, str(_REPO_ROOT))

from utils.paths import FILE_DATABASE_SECRETS  # noqa: E402
from utils.recovery import databases  # noqa: E402
from utils.recovery.base import DirectoryRecovery  # noqa: E402

UNIT_PATTERN = "svc-bkp-volume-2-local*.service"


class VolumeRecovery(DirectoryRecovery):
    unit_pattern = UNIT_PATTERN

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
        options = subprocess.run(
            [*docker, "volume", "inspect", "--format", "{{json .Options}}", volume],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if options not in ("", "null", "{}"):
            probe = (
                ["ssh", docker_host.split("://", 1)[-1], "mountpoint", "-q", mountpoint]
                if docker_host
                else ["mountpoint", "-q", mountpoint]
            )
            if subprocess.run(probe, check=False).returncode != 0:
                raise SystemExit(
                    f"volume {volume} declares its own backing store ({options}) but "
                    f"{mountpoint} is not mounted; docker mounts such volumes only while "
                    "a container holds them, so a restore now would land on the node "
                    "disk and be shadowed by the real backing store on the next mount. "
                    "Start a container that holds the volume, then retry."
                )
        target = (
            f"{docker_host.split('://', 1)[-1]}:{mountpoint}"
            if docker_host
            else mountpoint
        )
        super().__init__(source_dir, target, service_backup=service_backup)


class DatabaseRecovery(DirectoryRecovery):
    """Replay a generation's sql dumps, with the same safety-backup contract."""

    unit_pattern = UNIT_PATTERN

    def __init__(self, generation_dir: str, *, service_backup: bool = True) -> None:
        self.generation_dir = Path(generation_dir)
        super().__init__(generation_dir, generation_dir, service_backup=service_backup)

    def restore(self) -> None:
        databases.replay(self.generation_dir, FILE_DATABASE_SECRETS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source_dir",
        nargs="?",
        help="snapshot to restore from (e.g. <backups>/<machine-hash>/backup-docker-to-local/<generation>/<volume>/files)",
    )
    parser.add_argument("volume", nargs="?", help="docker volume name to restore into")
    parser.add_argument(
        "--databases",
        metavar="GENERATION_DIR",
        help="replay the generation's sql dumps instead of restoring one volume's files",
    )
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
    service_backup = not args.no_safety_backup

    if args.databases:
        if args.source_dir or args.volume:
            parser.error(
                "--databases takes the generation directory and no positionals"
            )
        if args.docker_host:
            parser.error(
                "--databases is local-only: the credentials live in the target host's "
                "own databases.csv, so run it on that host"
            )
        try:
            return DatabaseRecovery(args.databases, service_backup=service_backup).run()
        except databases.RecoveryError as error:
            print(f"FAIL: {error}", file=sys.stderr)
            return 1

    if not args.source_dir or not args.volume:
        parser.error("volume mode needs SOURCE_DIR and VOLUME")
    return VolumeRecovery(
        args.source_dir,
        args.volume,
        service_backup=service_backup,
        docker_host=args.docker_host,
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
