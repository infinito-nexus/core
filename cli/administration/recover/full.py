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

import re
import shlex
import subprocess
import sys
from pathlib import Path

from cli.administration.recover import paths, recoverers, remote, stage
from utils.recovery import manifest

_REPOS: tuple[tuple[str, str], ...] = (
    ("nfs", "backup-nfs-to-local"),
    ("volume", "backup-docker-to-local"),
    ("secrets", "backup-secrets-to-local"),
)
PULL_STAGE_PREFIX = "infinito-recover-pull-"
VOLUME_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def _newest_gen(root: Path, repo: str) -> Path | None:
    """Newest ``<root>/<machine-hash>/<repo>/<generation>`` directory, if any."""
    generations = sorted(root.glob(f"*/{repo}/*"))
    return generations[-1] if generations else None


def plan(root: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """(type, source) for each present repo, in order; volume per-volume.

    The volume repo contributes a database step after its file steps: the
    dumps have to land once the volumes are back and while the consumers are
    still down, which is where the caller has them.

    Returns:
        The steps, and the repos whose manifest could not be read. A repo that
        cannot state its layout is skipped rather than guessed at, but it must
        not take the others with it: recovering two repos of three beats
        recovering none because one manifest is corrupt.
    """
    steps: list[tuple[str, str]] = []
    unreadable: list[str] = []
    inside = root.resolve()
    for rtype, repo in _REPOS:
        generation = _newest_gen(root, repo)
        if generation is None:
            continue
        try:
            names = manifest.layout_of(generation)
        except ValueError as error:
            unreadable.append(f"{repo}: {error}")
            continue
        files_glob, dump_globs = manifest.globs_of(names)
        files_dir = names["files_dir"]
        if ":" in str(generation / files_dir):
            unreadable.append(
                f"{repo}: {generation / files_dir} holds a ':', "
                "which would read as a restore target"
            )
            continue
        if not generation.resolve().is_relative_to(inside):
            unreadable.append(f"{repo}: {generation} leads outside {root}")
            continue
        if rtype == "volume":
            for vol in sorted(generation.glob(files_glob)):
                volume = paths.volume_from_source(str(vol))
                if not VOLUME_NAME.fullmatch(volume):
                    unreadable.append(f"{repo}: {volume!r} is no docker volume name")
                elif not vol.resolve().is_relative_to(inside):
                    unreadable.append(f"{repo}: {vol} leads outside {root}")
                else:
                    steps.append((rtype, str(vol)))
            if any(hit for glob in dump_globs for hit in generation.glob(glob)):
                steps.append(("database", str(generation)))
        elif (generation / files_dir).is_dir():
            if (generation / files_dir).resolve().is_relative_to(inside):
                steps.append((rtype, str(generation / files_dir)))
            else:
                unreadable.append(
                    f"{repo}: {generation / files_dir} leads outside {root}"
                )
    return steps, unreadable


def _pull_cmd(source: str, destination: str) -> list[str]:
    """The rsync pulling a remote backup-root into *destination*.

    Args:
        source: ``[user@]host[:/path]``; a bare host means its standard root.
        destination: the local directory the tree lands in.
    """
    remote = source if ":" in source else f"{source}:{paths.BACKUP_ROOT}"
    return ["rsync", "-aHAX", f"{remote}/", f"{destination}/"]


def _pull_and_recover(source: str, target: str, *, service_backup: bool) -> int:
    """Pull *source* into a private stage, recover from it, then remove it.

    Args:
        source: ``[user@]host[:/path]`` whose backup tree is pulled.
        target: the host to restore onto.
        service_backup: run each role's pre-recover backup unit.
    """
    with stage.private(PULL_STAGE_PREFIX) as private:
        root = private / stage.TREE
        pull = _pull_cmd(source, str(root))
        print(f"# full: pull remote backup tree\n  {shlex.join(pull)}")
        if subprocess.run(pull, check=False).returncode != 0:
            return 2
        return _recover_under(
            root, target, preview=False, service_backup=service_backup
        )


def _remote_device_and_recover(
    source: str, target: str, *, service_backup: bool
) -> int:
    """Recover a remote device into a private stage, recover from it, remove it.

    Args:
        source: ``[user@]host:/device[:segments]``.
        target: the host to restore onto.
        service_backup: run each role's pre-recover backup unit.
    """
    with stage.private(remote.STAGE_PREFIX) as private:
        returncode, root = remote.run(
            source,
            local_stage=private,
            preview=False,
            service_backup=service_backup,
            passphrase_stdin=not sys.stdin.isatty(),
        )
        if root is None:
            return returncode
        return _recover_under(
            root, target, preview=False, service_backup=service_backup
        )


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
    steps, unreadable = plan(root)
    for problem in unreadable:
        print(f"# full: SKIPPED {problem}", file=sys.stderr)
    if not steps:
        print(f"# full: no backup repos found under {root}")
        return 1
    returncode = 2 if unreadable else 0
    for rtype, files_dir in steps:
        cmd = recoverers.RECOVERERS[rtype].command(
            files_dir, service_backup=service_backup, target=target
        )
        print(f"# full {rtype}  {target}: {shlex.join(cmd)}")
        if not preview:
            failed = subprocess.run(cmd, check=False).returncode
            if failed != 0:
                return failed
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
    elif remote.is_block_device(source):
        if not preview:
            return _remote_device_and_recover(
                source, target, service_backup=service_backup
            )
        remote.run(
            source,
            local_stage=stage.preview(remote.STAGE_PREFIX),
            preview=True,
            service_backup=service_backup,
            passphrase_stdin=not sys.stdin.isatty(),
        )
        print(
            "  # then discover + recover nfs -> volume -> secrets under the pulled root"
        )
        return 0
    else:
        if not preview:
            return _pull_and_recover(source, target, service_backup=service_backup)
        placeholder = stage.preview(PULL_STAGE_PREFIX) / stage.TREE
        pull = _pull_cmd(source, str(placeholder))
        print(f"# full: pull remote backup tree\n  {shlex.join(pull)}")
        print("  # then discover + recover nfs -> volume -> secrets")
        return 0
    return _recover_under(root, target, preview=preview, service_backup=service_backup)
