#!/usr/bin/env python3
# nocheck: mirrored-unit-test - subclasses utils.recovery.base and is exercised
# collectively by tests/unit/python/utils/recovery/test_role_recover_scripts.py; a
# per-role copy would assert the base class twice over
"""Restore an NFS export subtree from a backup snapshot.

Runs the role's deployed backup unit first (the usual differential
``backup-nfs-to-local`` generation of the live export), then mirrors the
snapshot into the target (``rsync -aHAX --delete``). Run on the host
serving the export with every consuming stack stopped; NFS clients
re-mount on redeploy.

Usage:
    recover.py SOURCE_DIR TARGET_DIR [--no-safety-backup]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]  # nocheck: project-root-import
sys.path.insert(0, str(_REPO_ROOT))

from utils.recovery.base import DirectoryRecovery, is_remote  # noqa: E402
from utils.storage.nfs import STATE_SUBDIR  # noqa: E402


class NfsExportRecovery(DirectoryRecovery):
    unit_pattern = "svc-bkp-nfs-2-local*.service"

    @property
    def rsync_extra_args(self) -> tuple[str, ...]:
        return (
            f"--filter=protect /{STATE_SUBDIR}/backup",
            f"--exclude=/{STATE_SUBDIR}/backup",
            *(
                f"--filter=protect /{STATE_SUBDIR}/{name}"
                for name in self.volumes_missing_from_snapshot()
            ),
        )

    def volumes_missing_from_snapshot(self) -> list[str]:
        """Volume directories of the live export the snapshot does not hold.

        Returns:
            The sorted names under the state path; empty when either side is
            remote and cannot be listed.
        """
        if is_remote(str(self.source_dir)) or is_remote(str(self.target_dir)):
            return []
        live = self.target_dir / STATE_SUBDIR
        if not live.is_dir():
            return []
        kept = self.source_dir / STATE_SUBDIR
        return sorted(
            entry.name
            for entry in live.iterdir()
            if entry.is_dir() and not (kept / entry.name).exists()
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", help="snapshot directory to restore from")
    parser.add_argument("target_dir", help="live export subtree to restore into")
    parser.add_argument(
        "--no-safety-backup",
        action="store_true",
        help="skip the pre-recover safety backup of the current target (only when it holds nothing worth saving)",
    )
    args = parser.parse_args()
    return NfsExportRecovery(
        args.source_dir, args.target_dir, service_backup=not args.no_safety_backup
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
