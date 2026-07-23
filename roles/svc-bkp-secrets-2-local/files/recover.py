#!/usr/bin/env python3
"""Restore host-generated secret material from a backup snapshot.

Runs the role's deployed backup unit first (a fresh differential
``backup-secrets-to-local`` generation of the live material), then
mirrors each present subtree of the snapshot back to its fixed system
path (``rsync -a --delete``): secrets, the self-signed CA, the Let's
Encrypt tree and the ACME DNS credentials. The ``node`` subtree (ssh
host keys + machine-id) is restored only with ``--restore-node-identity``
because overwriting the running machine-id / ssh host keys changes the
host's identity mid-flight -- do it on a fresh host after total loss.

Usage:
    recover.py FILES_DIR [--restore-node-identity] [--no-safety-backup] [--target-host HOST]

where FILES_DIR is the ``<generation>/files`` directory of a
backup-secrets-to-local generation.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]  # nocheck: project-root-import
sys.path.insert(0, str(_REPO_ROOT))

from utils.paths import DIR_SECRETS  # noqa: E402
from utils.recovery.base import DirectoryRecovery  # noqa: E402


class SecretsRecovery(DirectoryRecovery):
    unit_pattern = "svc-bkp-secrets-2-local*.service"


def _software_domain() -> str:
    general = _REPO_ROOT / "group_vars" / "all" / "00_general.yml"
    text = general.read_text()  # nocheck: cache-read - repo SPOT on the recovering host
    for line in text.splitlines():
        if line.startswith("SOFTWARE_NAME:"):
            value = line.split(":", 1)[1].split("#", 1)[0].strip()
            return value.strip("\"'").lower()
    raise SystemExit("SOFTWARE_NAME not found in group_vars/all/00_general.yml")


def _targets(domain: str) -> dict[str, str]:
    return {
        "secrets": str(DIR_SECRETS),
        "ca": f"/etc/{domain}/ca",
        "acme": "/etc/letsencrypt",
        "certbot": "/etc/certbot",
    }


def _restore_node_identity(node_dir: Path) -> None:
    machine_id = node_dir / "machine-id"
    if machine_id.is_file():
        shutil.copy2(machine_id, "/etc/machine-id")
        print("OK: restored /etc/machine-id")
    for key in node_dir.glob("ssh_host_*"):
        shutil.copy2(key, Path("/etc/ssh") / key.name)
        print(f"OK: restored /etc/ssh/{key.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files_dir", help="<generation>/files directory to restore from"
    )
    parser.add_argument(
        "--restore-node-identity",
        action="store_true",
        help="also restore ssh host keys + machine-id (only on a fresh host)",
    )
    parser.add_argument(
        "--no-safety-backup",
        action="store_true",
        help="skip the pre-recover safety backup of the current target (only when it holds nothing worth saving)",
    )
    parser.add_argument(
        "--target-host",
        help="[user@]host to rsync the secret subtrees onto over ssh (recover onto a remote machine)",
    )
    args = parser.parse_args()

    files_dir = Path(args.files_dir)
    if not files_dir.is_dir():
        raise SystemExit(f"ERROR: snapshot {files_dir} does not exist")

    domain = _software_domain()
    targets = _targets(domain)

    subtrees = [
        (name, files_dir / name, target)
        for name, target in targets.items()
        if (files_dir / name).is_dir()
    ]
    if not subtrees:
        raise SystemExit(f"ERROR: no restorable subtree under {files_dir}")

    remote = args.target_host
    ran_backup = False
    for name, source, target in subtrees:
        dest = f"{remote}:{target}" if remote else target
        if not remote:
            Path(target).mkdir(parents=True, exist_ok=True)
        recovery = SecretsRecovery(
            str(source), dest, service_backup=not args.no_safety_backup
        )
        if recovery.service_backup and not remote and not ran_backup:
            recovery.backup_target()
            ran_backup = True
        recovery.restore()
        print(f"OK: {name} restored into {dest}")

    if args.restore_node_identity and (files_dir / "node").is_dir():
        if remote:
            print(
                "skip: --restore-node-identity is local-only (not applied to a remote target)"
            )
        else:
            _restore_node_identity(files_dir / "node")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
