#!/usr/bin/env python3
"""Restore the local backup root from the encrypted backup device.

Opens the LUKS device (interactive passphrase prompt, or stdin with
``--passphrase-stdin``), mounts it, picks the newest device snapshot
(any machine hash: a fresh host after total loss has a new
/etc/machine-id) and mirrors it into the target
(``rsync -a --delete``), then unmounts and closes the device again.
No pre-recover service backup runs: the device itself is the backup
this role maintains.

Usage:
    recover.py DEVICE MOUNT_DIR TARGET_DIR [--device-target SUBPATH]
               [--snapshot TIMESTAMP] [--passphrase-stdin]

``--device-target`` is the role's ``services.local-2-device.target``
subpath the backup unit synced into (snapshots live under
``<mount>/<target>/...``, not directly under the mountpoint).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]  # nocheck: project-root-import
sys.path.insert(0, str(_REPO_ROOT))

from utils.recovery.base import DirectoryRecovery  # noqa: E402

_MAPPER = "svc-bkp-local-2-device-recover"


class DeviceRecovery(DirectoryRecovery):
    unit_pattern = "svc-bkp-local-2-device*.service"

    def __init__(self, source_dir: str, target_dir: str) -> None:
        super().__init__(source_dir, target_dir, service_backup=False)


def _newest_snapshot(mount_dir: Path, snapshot: str | None) -> Path:
    candidates = sorted(
        mount_dir.glob("*/svc-bkp-local-2-device/*"),
        key=lambda p: p.name,
    )
    if snapshot:
        candidates = [p for p in candidates if p.name == snapshot]
    if not candidates:
        raise SystemExit(
            f"ERROR: no device snapshot under {mount_dir}/*/svc-bkp-local-2-device"
            + (f" matching {snapshot}" if snapshot else "")
        )
    return candidates[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", help="LUKS device or image file to open")
    parser.add_argument("mount_dir", help="directory to mount the opened device on")
    parser.add_argument("target_dir", help="local backup root to restore into")
    parser.add_argument(
        "--device-target",
        default="",
        help="services.local-2-device.target subpath holding the snapshots on the device",
    )
    parser.add_argument(
        "--snapshot",
        help="snapshot timestamp to restore (default: newest on the device)",
    )
    parser.add_argument(
        "--passphrase-stdin",
        action="store_true",
        help="read the LUKS passphrase from stdin instead of the terminal",
    )
    args = parser.parse_args()

    open_cmd = ["cryptsetup", "luksOpen", args.device, _MAPPER]
    if args.passphrase_stdin:
        open_cmd.insert(2, "--key-file=-")
    subprocess.run(open_cmd, check=True)
    mount_dir = Path(args.mount_dir)
    try:
        mount_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["mount", f"/dev/mapper/{_MAPPER}", str(mount_dir)], check=True)
        try:
            snapshot_root = mount_dir / args.device_target.lstrip("/")
            snapshot = _newest_snapshot(snapshot_root, args.snapshot)
            print(f"OK: restoring device snapshot {snapshot}")
            return DeviceRecovery(str(snapshot / "backup"), args.target_dir).run()
        finally:
            subprocess.run(["umount", str(mount_dir)], check=False)
    finally:
        subprocess.run(["cryptsetup", "luksClose", _MAPPER], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
