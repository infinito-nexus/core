from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text

from .common import make_compose

if TYPE_CHECKING:
    from pathlib import Path

SERVICE = "quality"
PROFILE = "tools"
GITDIR_PREFIX = "gitdir:"
COMMENT_PREFIX = "#"


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "quality",
        help="Run quality in its compose service (profile tools) against this checkout.",
    )
    p.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments for quality, such as: -- check --staged.",
    )
    p.set_defaults(_handler=handler)


def git_dir(root: Path) -> Path:
    """
    Args:
        root: the checkout.

    Returns:
        Its ``.git`` directory, or the directory the ``gitdir:`` line of its
        ``.git`` file names, resolved against ``root``.
    """
    dot_git = root / ".git"
    if not dot_git.is_file():
        return dot_git
    pointer = read_text(str(dot_git)).strip().removeprefix(GITDIR_PREFIX).strip()
    return (root / pointer).resolve()


def common_dir(gitdir: Path) -> Path:
    """
    Args:
        gitdir: a git directory, as :func:`git_dir` returns it.

    Returns:
        The directory its ``commondir`` file names, resolved against
        ``gitdir``, or ``gitdir`` itself when it has none.
    """
    marker = gitdir / "commondir"
    if not marker.is_file():
        return gitdir
    return (gitdir / read_text(str(marker)).strip()).resolve()


def alternate_object_dirs(objects: Path) -> list[Path]:
    """
    Args:
        objects: an object directory.

    Returns:
        Every object directory its ``info/alternates`` names, and theirs in
        turn, each resolved against the directory that lists it, once each
        and never ``objects`` itself.
    """
    found: list[Path] = []
    pending = [objects]
    while pending:
        current = pending.pop(0)
        alternates = current / "info" / "alternates"
        if not alternates.is_file():
            continue
        for line in read_text(str(alternates)).splitlines():
            entry = line.strip()
            if not entry or entry.startswith(COMMENT_PREFIX):
                continue
            target = (current / entry).resolve()
            if target != objects and target not in found:
                found.append(target)
                pending.append(target)
    return found


def git_mounts(root: Path) -> list[str]:
    """
    Args:
        root: the checkout the service mounts at ``/src``.

    Returns:
        One read-only bind per directory outside ``root`` that git needs to
        read the checkout, at its own absolute path: the git and common
        directory of a linked worktree and every alternate object directory
        of a ``--shared`` or ``--reference`` clone. A directory inside
        another bound one is left out.
    """
    gitdir = git_dir(root)
    common = common_dir(gitdir)
    needed = {gitdir, common, *alternate_object_dirs(common / "objects")}
    kept: list[Path] = []
    for path in sorted(needed, key=lambda item: (len(item.parts), str(item))):
        if path.is_relative_to(root) or any(map(path.is_relative_to, kept)):
            continue
        kept.append(path)
    return [f"{path}:{path}:ro" for path in kept]


def handler(args: argparse.Namespace) -> int:
    quality_args = args.args[1:] if args.args[:1] == ["--"] else list(args.args)
    if not quality_args:
        raise SystemExit("quality needs its arguments, such as: -- check --staged")
    mounts = [flag for mount in git_mounts(PROJECT_ROOT) for flag in ("-v", mount)]
    r = make_compose().run(
        ["--profile", PROFILE, "run", "--rm", *mounts, SERVICE, *quality_args],
        check=False,
    )
    return int(r.returncode)
