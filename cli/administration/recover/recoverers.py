"""Recoverer classes: one per svc-bkp-* recovery type.

Each Recoverer parses and validates its own colon-encoded ``source`` and
builds the role's ``files/recover.py`` invocation. Colon segments are
classified by shape: an ABSOLUTE path is the restore destination (replacing
a --target flag); for device a RELATIVE segment is the on-device snapshot
subpath and an all-digit ``YYYYMMDDHHMMSS`` segment is the generation to
restore. No colon means the derived standard-layout target and the newest
generation. The uniform console command ``<type> <source> <target>``
dispatches to one Recoverer via :data:`RECOVERERS`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from cli.administration.recover import paths
from utils import PROJECT_ROOT


def is_remote(source: str) -> bool:
    """A source not starting with ``/`` is a remote ``[user@]host:/path`` (rsync pulls it)."""
    return not source.startswith("/")


def split_target(source: str) -> tuple[str, str | None]:
    """Split ``<path>:<absolute-target>`` -> (path, target).

    A remote source (``[user@]host:/path``) is returned as-is with the
    default target (its colon is the rsync host separator). Otherwise a
    colon suffix is a restore target only when absolute; a relative suffix
    is rejected here (device parses those itself).
    """
    if is_remote(source):
        return source, None
    head, sep, tail = source.partition(":")
    if not sep:
        return source, None
    if not tail.startswith("/"):
        raise ValueError(f"restore target after ':' must be an absolute path: {tail!r}")
    return head, tail


def remote_target(target: str) -> bool:
    """A target other than localhost is a remote ``[user@]host`` reached over ssh."""
    return target not in ("localhost", "local")


class Recoverer(ABC):
    """One recovery type backed by a role's ``files/recover.py``."""

    name: str
    role: str
    summary: str
    no_backup_flag: bool = True

    def script(self) -> str:
        return str(PROJECT_ROOT / "roles" / self.role / "files" / "recover.py")

    @abstractmethod
    def args(self, source: str, target: str) -> list[str]:
        """recover.py positional/type args, parsed and validated from source.

        ``target`` is the host to restore onto (``localhost`` = local); a
        remote host makes the recover push over ssh (rsync target / docker
        host / secret paths gain the remote prefix).
        """

    def extra_flags(self, *, passphrase_stdin: bool) -> list[str]:
        return []

    def command(
        self,
        source: str,
        *,
        service_backup: bool = True,
        passphrase_stdin: bool = False,
        target: str = "localhost",
    ) -> list[str]:
        argv = self.args(source, target)
        if not service_backup and self.no_backup_flag:
            argv.append("--no-safety-backup")
        argv += self.extra_flags(passphrase_stdin=passphrase_stdin)
        return ["python3", self.script(), *argv]


class DeviceRecoverer(Recoverer):
    name = "device"
    role = "svc-bkp-local-2-device"
    summary = "Encrypted LUKS device -> local backup root"
    no_backup_flag = False

    def args(self, source: str, target: str) -> list[str]:
        if is_remote(source):
            raise ValueError(
                "device: source must be a local block device or image path"
            )
        device, subpath, snapshot, restore_root = self._parse(source)
        if not device:
            raise ValueError("device: empty device path")
        argv = [device, paths.RECOVER_MOUNT, restore_root or paths.BACKUP_ROOT]
        if subpath:
            argv += ["--device-target", subpath]
        if snapshot:
            argv += ["--snapshot", snapshot]
        return argv

    @staticmethod
    def _parse(source: str) -> tuple[str, str, str, str | None]:
        device, *rest = source.split(":")
        subpath, snapshot, target = "", "", None
        for segment in rest:
            if not segment:
                continue
            if segment.startswith("/"):
                target = segment
            elif segment.isdigit():
                snapshot = segment
            else:
                subpath = segment
        return device, subpath, snapshot, target

    def extra_flags(self, *, passphrase_stdin: bool) -> list[str]:
        return ["--passphrase-stdin"] if passphrase_stdin else []


class NfsRecoverer(Recoverer):
    name = "nfs"
    role = "svc-bkp-nfs-2-local"
    summary = "Snapshot -> live NFS export subtree"

    def args(self, source: str, target: str) -> list[str]:
        snapshot, override = split_target(source)
        if not snapshot:
            raise ValueError("nfs: empty source snapshot")
        dest = override or paths.NFS_EXPORT_STATE
        if remote_target(target):
            dest = f"{target}:{dest}"
        return [snapshot, dest]


class VolumeRecoverer(Recoverer):
    name = "volume"
    role = "svc-bkp-volume-2-local"
    summary = "Snapshot -> docker volume (name from the source path)"

    def args(self, source: str, target: str) -> list[str]:
        volume = paths.volume_from_source(source)
        if not volume:
            raise ValueError(f"volume: cannot derive a volume name from {source!r}")
        argv = [source, volume]
        if remote_target(target):
            argv += ["--docker-host", f"ssh://{target}"]
        return argv


class SecretsRecoverer(Recoverer):
    name = "secrets"
    role = "svc-bkp-secrets-2-local"
    summary = "Snapshot -> host secret paths (secrets, CA, Let's Encrypt, ACME)"

    def args(self, source: str, target: str) -> list[str]:
        if is_remote(source):
            raise ValueError(
                "secrets: remote source not supported; pull first or use 'full'"
            )
        if not source:
            raise ValueError("secrets: empty source")
        argv = [source]
        if remote_target(target):
            argv += ["--target-host", target]
        return argv


_RECOVERERS: tuple[Recoverer, ...] = (
    DeviceRecoverer(),
    NfsRecoverer(),
    VolumeRecoverer(),
    SecretsRecoverer(),
)
RECOVERERS: dict[str, Recoverer] = {r.name: r for r in _RECOVERERS}
ORDER: tuple[str, ...] = tuple(r.name for r in _RECOVERERS)
