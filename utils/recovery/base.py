"""Abstract recover flow shared by every ``svc-bkp-*`` role.

A recover mirrors a snapshot into a live target directory
(``rsync -a --delete``), so the target's current state would be lost
without a net. The flow therefore first runs the role's deployed backup
service (``systemctl start`` on the role's unit), which applies the
usual differential backup logic to the live data before anything is
overwritten. Roles subclass :class:`DirectoryRecovery`, set
``unit_pattern`` and ship a thin ``files/recover.py`` CLI around it
(enforced by ``tests/lint/ansible/roles/test_bkp_roles_have_recover.py``).

Host-agnostic: source and target may be a local path or a remote
``[user@]host:/path`` (rsync pushes/pulls over ssh). A remote target
skips the local pre-recover safety backup, since that host's live data
is the remote's concern.
"""

from __future__ import annotations

import subprocess
from abc import ABC
from pathlib import Path


def is_remote(location: str) -> bool:
    """A location not starting with ``/`` is a remote ``[user@]host:/path``."""
    return not location.startswith("/")


class DirectoryRecovery(ABC):
    """Service-backed recovery for a directory target.

    Args:
        source_dir: snapshot directory to restore from.
        target_dir: live directory to restore into.
        service_backup: run the role's backup unit first (default);
            disable only when the target holds nothing worth saving.
    """

    unit_pattern: str
    rsync_extra_args: tuple[str, ...] = ()

    def __init__(
        self, source_dir: str, target_dir: str, *, service_backup: bool = True
    ) -> None:
        if not getattr(self, "unit_pattern", ""):
            raise ValueError(f"{type(self).__name__} must set unit_pattern")
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir)
        self.service_backup = service_backup
        if not is_remote(str(self.source_dir)) and not self.source_dir.is_dir():
            raise SystemExit(f"ERROR: snapshot {self.source_dir} does not exist")
        if not is_remote(str(self.target_dir)) and not self.target_dir.is_dir():
            raise SystemExit(
                f"ERROR: target {self.target_dir} does not exist; refusing to "
                "create it implicitly"
            )

    def _backup_units(self) -> list[str]:
        listing = subprocess.run(
            [
                "systemctl",
                "list-unit-files",
                self.unit_pattern,
                "--no-legend",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return [line.split()[0] for line in listing.splitlines() if line.split()]

    def backup_target(self) -> None:
        """Run the role's deployed backup unit against the live data."""
        units = self._backup_units()
        if not units:
            raise SystemExit(
                f"ERROR: no unit matches {self.unit_pattern}; deploy the role "
                "first or pass --no-safety-backup when the target holds "
                "nothing worth saving"
            )
        for unit in units:
            print(f"OK: running backup unit {unit} before the recover")
            subprocess.run(["systemctl", "start", unit], check=True)

    def restore(self) -> None:
        subprocess.run(
            [
                "rsync",
                "-a",
                "--numeric-ids",
                "--delete",
                *self.rsync_extra_args,
                f"{self.source_dir}/",
                f"{self.target_dir}/",
            ],
            check=True,
        )
        print(f"OK: {self.target_dir} restored from {self.source_dir}")

    def run(self) -> int:
        if self.service_backup and not is_remote(str(self.target_dir)):
            self.backup_target()
        self.restore()
        return 0
