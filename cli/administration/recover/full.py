"""'full' recovery: recover every backup-stored type against a target host.

Resolves a source to a local backup-root, then discovers the newest
generation of each repo present under it and recovers each type in order
(nfs -> volume -> secrets) against the target via the per-type Recoverers.
The source is one of:

- a local backup-root directory (used directly),
- a remote ``[user@]host[:/path]`` (its backup tree is rsync-pulled first),
- a LUKS device / image (recovered first via the device step, which
  restores the tree to its restore-root, then discovered under that root).
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from cli.administration.recover import paths, recoverers, remote

_REPOS: tuple[tuple[str, str], ...] = (
    ("nfs", "backup-nfs-to-local"),
    ("volume", "backup-docker-to-local"),
    ("secrets", "backup-secrets-to-local"),
)
PULL_STAGE = "/tmp/infinito-recover-pull"  # noqa: S108 - operator recovery staging dir


def _newest_gen(root: Path, repo: str) -> Path | None:
    """Newest ``<root>/<machine-hash>/<repo>/<generation>`` directory, if any."""
    generations = sorted(root.glob(f"*/{repo}/*"))
    return generations[-1] if generations else None


def plan(root: Path) -> list[tuple[str, str]]:
    """(type, source-files-dir) for each present repo, in order; volume per-volume."""
    steps: list[tuple[str, str]] = []
    for rtype, repo in _REPOS:
        generation = _newest_gen(root, repo)
        if generation is None:
            continue
        if rtype == "volume":
            steps += [(rtype, str(vol)) for vol in sorted(generation.glob("*/files"))]
        elif (generation / "files").is_dir():
            steps.append((rtype, str(generation / "files")))
    return steps


def _pull_cmd(source: str) -> list[str]:
    remote = source if ":" in source else f"{source}:{paths.BACKUP_ROOT}"
    return ["rsync", "-a", f"{remote}/", f"{PULL_STAGE}/"]


def _is_device(source: str) -> bool:
    """A local source whose leading segment is a block device or an image file."""
    leading = Path(source.split(":", 1)[0])
    return leading.is_block_device() or leading.is_file()


def _device_restore_root(source: str) -> str:
    """The device source's restore-root (its absolute colon segment, else the default)."""
    for segment in source.split(":")[1:]:
        if segment.startswith("/"):
            return segment
    return paths.BACKUP_ROOT


def _recover_under(
    root: Path, target: str, *, preview: bool, service_backup: bool
) -> int:
    steps = plan(root)
    if not steps:
        print(f"# full: no backup repos found under {root}")
        return 1
    returncode = 0
    for rtype, files_dir in steps:
        cmd = recoverers.RECOVERERS[rtype].command(
            files_dir, service_backup=service_backup, target=target
        )
        print(f"# full {rtype}  {target}: {shlex.join(cmd)}")
        if not preview:
            returncode = subprocess.run(cmd, check=False).returncode
            if returncode != 0:
                return returncode
    return returncode


def run(source: str, target: str, *, preview: bool, service_backup: bool) -> int:
    if source.startswith("/") and _is_device(source):
        device_cmd = recoverers.RECOVERERS["device"].command(
            source,
            service_backup=service_backup,
            passphrase_stdin=not sys.stdin.isatty(),
            target=target,
        )
        print(f"# full device  {target}: {shlex.join(device_cmd)}")
        if preview:
            print(
                "  # then discover + recover nfs -> volume -> secrets under the restored root"
            )
            return 0
        if subprocess.run(device_cmd, check=False).returncode != 0:
            return 2
        root = Path(_device_restore_root(source))
    elif source.startswith("/"):
        root = Path(source)
    elif remote.split_host(source)[1].split(":", 1)[0].startswith("/dev/"):
        returncode, root_str = remote.run(
            source,
            preview=preview,
            service_backup=service_backup,
            passphrase_stdin=not sys.stdin.isatty(),
        )
        if preview:
            print(
                "  # then discover + recover nfs -> volume -> secrets under the pulled root"
            )
            return 0
        if returncode != 0:
            return returncode
        root = Path(root_str)
    else:
        pull = _pull_cmd(source)
        print(f"# full: pull remote backup tree\n  {shlex.join(pull)}")
        if preview:
            print("  # then discover + recover nfs -> volume -> secrets")
            return 0
        subprocess.run(["mkdir", "-p", PULL_STAGE], check=False)
        if subprocess.run(pull, check=False).returncode != 0:
            return 2
        root = Path(PULL_STAGE)
    return _recover_under(root, target, preview=preview, service_backup=service_backup)
