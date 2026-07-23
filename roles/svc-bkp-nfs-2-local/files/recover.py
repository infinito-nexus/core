#!/usr/bin/env python3
"""Restore an NFS export subtree from a backup snapshot.

Runs the role's deployed backup unit first (the usual differential
``backup-nfs-to-local`` generation of the live export), then mirrors the
snapshot into the target (``rsync -a --delete``). Run on the host
serving the export with every consuming stack stopped; NFS clients
re-mount on redeploy.

Usage:
    recover.py SOURCE_DIR TARGET_DIR [--no-safety-backup]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]  # nocheck: project-root-import
sys.path.insert(0, str(_REPO_ROOT))

from utils.recovery.base import DirectoryRecovery  # noqa: E402
from utils.storage.nfs import STATE_SUBDIR  # noqa: E402


class NfsExportRecovery(DirectoryRecovery):
    unit_pattern = "svc-bkp-nfs-2-local*.service"
    rsync_extra_args = (
        f"--filter=protect /{STATE_SUBDIR}/backup",
        f"--exclude=/{STATE_SUBDIR}/backup",
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
