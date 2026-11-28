from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from utils.runner import POOL_RUNNER_KEY

if TYPE_CHECKING:
    from collections.abc import Sequence

ENTRY = Path("scripts") / "tests" / "deploy" / "job" / "entry.sh"
GIT = ".git"
GITDIR = "gitdir:"
CUSTOM_ENV = "custom.env"
NEVER_LISTED = (".env", CUSTOM_ENV)
MANIFEST = "checkout.files"
PRIVATE = 0o600
LISTING = ("git", "ls-files", "-z", "--cached", "--others", "--exclude-standard")
POOL_SETTINGS = {POOL_RUNNER_KEY: "true", "INFINITO_DEPLOY_VIA_POOL": "false"}


def _within(path: Path | str, parent: Path | str) -> bool:
    return Path(os.path.realpath(path)).is_relative_to(os.path.realpath(parent))


def _below(path: Path | str, parent: Path | str) -> bool:
    return _within(path, parent) and os.path.realpath(path) != os.path.realpath(parent)


def confined(checkout: str, roots: Sequence[Path]) -> Path | None:
    """Args:
        checkout: a job's checkout as its record names it.
        roots: the worktree roots the runner mounts.

    Returns:
        The checkout with every link resolved, None when it is no absolute
        path, resolves outside every root or to a root itself, or holds no
        job entry.
    """
    if not Path(checkout).is_absolute() or "\0" in checkout:
        return None
    real = Path(os.path.realpath(checkout))
    inside = any(_below(real, root) for root in roots)
    return real if inside and (real / ENTRY).is_file() else None


def _own(target: Path, install: Path) -> Path:
    if not _within(target.parent, install):
        raise OSError(f"{target.parent} resolves outside {install}")
    if target.is_symlink():
        target.unlink()
    target.mkdir(exist_ok=True)
    return target


def _gitdir(checkout: Path) -> Path:
    dot = checkout / GIT
    if dot.is_dir() and not dot.is_symlink():
        return Path(os.path.realpath(dot))
    with dot.open(encoding="utf-8") as handle:
        line = handle.readline().strip()
    if not line.startswith(GITDIR):
        raise OSError(f"{dot} names no {GITDIR}")
    gitdir = Path(os.path.realpath(checkout / line.removeprefix(GITDIR).strip()))
    if not gitdir.is_dir():
        raise OSError(f"{dot} points to {gitdir}, which this runner does not mount")
    return gitdir


def _place(source: Path, destination: Path, target: Path) -> None:
    if not _within(destination.parent, target):
        raise OSError(f"{destination.parent} resolves outside {target}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_dir() and not destination.is_symlink():
        destination.rmdir()
    elif destination.is_symlink() or destination.exists():
        destination.unlink()
    if source.is_symlink():
        destination.symlink_to(source.readlink())
    else:
        shutil.copy2(source, destination)


def _listed(checkout: Path) -> list[str]:
    listed = subprocess.run(LISTING, cwd=checkout, capture_output=True, check=True)
    names = (os.fsdecode(raw) for raw in listed.stdout.split(b"\0") if raw)
    return [
        name
        for name in names
        if name not in NEVER_LISTED
        and ((checkout / name).is_symlink() or (checkout / name).is_file())
    ]


def _manifest(install: Path) -> set[str]:
    path = install / MANIFEST
    if path.is_symlink() or not path.is_file():
        return set()
    with path.open(encoding="utf-8") as handle:
        return {name for name in handle.read().split("\0") if name}


def _replace(path: Path, text: str) -> None:
    if path.is_symlink() or path.exists():
        path.unlink()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, PRIVATE), "w", encoding="utf-8") as handle:
        handle.write(text)


def _drop(target: Path, name: str) -> None:
    path = target / name
    if _within(path.parent, target) and (path.is_symlink() or path.is_file()):
        path.unlink()


def _custom_env(checkout: Path, target: Path) -> None:
    source = checkout / CUSTOM_ENV
    kept: list[str] = []
    if source.is_file() and not source.is_symlink():
        with source.open(encoding="utf-8") as handle:
            kept = [
                line.rstrip("\n")
                for line in handle
                if line.removeprefix("export ").split("=", 1)[0].strip()
                not in POOL_SETTINGS
            ]
    pinned = [f"{key}={value}" for key, value in POOL_SETTINGS.items()]
    _replace(target / CUSTOM_ENV, "\n".join([*kept, *pinned]) + "\n")


def copy_checkout(checkout: Path, target: Path, install: Path) -> Path:
    """Args:
        checkout: the job's checkout, resolved inside the worktree roots.
        target: the runner's own directory the job runs from.
        install: the runner's install directory, which must hold the target
            and keeps the list of files copied last.

    Returns:
        The target mirroring every file git sees in the checkout, tracked or
        untracked and not ignored, links kept as links, never ``.env``: a
        file copied before that git no longer lists goes, while files the
        job wrote itself stay. Beside them its ``custom.env``, the
        checkout's own with :data:`POOL_SETTINGS` pinned and mode 0600 like
        every file the runner writes itself, and a ``.git`` file
        naming the checkout's git directory as the runner mounts it, so
        ``git rev-parse`` works in the copy while the worktree stays a
        read-only mount.

    Raises:
        OSError: the target lies outside the install directory, the
            checkout's git directory is not mounted, or a file cannot be read
            or written.
        subprocess.CalledProcessError: git cannot list the checkout.
    """
    gitdir = _gitdir(checkout)
    names = _listed(checkout)
    _own(target, install)
    for name in sorted(_manifest(install) - set(names)):
        _drop(target, name)
    for name in names:
        _place(checkout / name, target / name, target)
    _custom_env(checkout, target)
    _replace(target / GIT, f"{GITDIR} {gitdir}\n")
    _replace(install / MANIFEST, "\0".join(names))
    return target
