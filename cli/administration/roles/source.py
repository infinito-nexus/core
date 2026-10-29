"""Check the source of a custom role and stage its content."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from utils.roles.custom import CustomRoleError

if TYPE_CHECKING:
    from .declaration import Source

_COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__")
_DROPPED_ENV = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_ASKPASS",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
        "SSH_ASKPASS",
    }
)


def check(group: str, source: Source, placements: list[Path], roles_dir: Path) -> None:
    """Refuse a source before anything is fetched.

    Args:
        group: the custom role's inventory group.
        source: its validated declaration.
        placements: every ``roles/web-app-cst-*`` entry that exists now.
        roles_dir: the core ``roles/`` the role is placed in.

    Raises:
        CustomRoleError: for a missing local directory, a local source the
            pull would delete, or a version that is no tag or full commit SHA.
    """
    if source.local:
        _check_local(group, source, [roles_dir / group, *placements], roles_dir)
    if source.version is None or source.commit:
        return
    refs = {
        line.split("\t", 1)[1]
        for line in _git(
            None, ["ls-remote", "--", source.url], f"{group}: git ls-remote failed"
        )
        .decode(errors="replace")
        .splitlines()
        if "\t" in line
    }
    if f"refs/heads/{source.version}" in refs:
        raise CustomRoleError(
            f"{group}: source.version '{source.version}' names a branch; pin a tag or a full commit SHA"
        )
    if f"refs/tags/{source.version}" not in refs:
        raise CustomRoleError(
            f"{group}: source.version '{source.version}' is neither a tag nor a full commit SHA"
        )


def stage(group: str, source: Source, target: Path) -> str:
    """Copy the role of ``source`` into ``target`` and describe what was copied.

    Args:
        group: the custom role's inventory group.
        source: a checked declaration.
        target: a path that does not exist yet; it becomes the role directory.

    Returns:
        The source and, for a pinned version, the resolved commit.

    Raises:
        CustomRoleError: the source cannot be read, or it holds an entry,
            such as a link to an absolute path, the pull refuses to unpack.
    """
    if source.version is None:
        content = Path(source.url) / source.path
        if not content.is_dir():
            raise CustomRoleError(
                f"{group}: source.path is not a directory in the source"
            )
        shutil.copytree(content, target, symlinks=True, ignore=_COPY_IGNORE)
        return source.describe()
    with tempfile.TemporaryDirectory(prefix="infinito-custom-role-") as scratch:
        _git(scratch, ["init", "--quiet", "--bare"], f"{group}: git init failed")
        _git(
            scratch,
            [
                "fetch",
                "--quiet",
                "--depth",
                "1",
                "--no-tags",
                "--",
                source.url,
                source.version,
            ],
            f"{group}: git fetch of {source.version} failed",
        )
        commit = (
            _git(
                scratch,
                ["rev-parse", "--verify", "FETCH_HEAD^{commit}"],
                f"{group}: {source.version} names no commit",
            )
            .decode()
            .strip()
        )
        tree = f"{commit}:{source.path}"
        kind = _git(
            scratch,
            ["cat-file", "-t", tree],
            f"{group}: source.path is not a directory in the source",
        )
        if kind.decode().strip() != "tree":
            raise CustomRoleError(
                f"{group}: source.path is not a directory in the source"
            )
        archive = _git(
            scratch,
            ["archive", "--format=tar", tree],
            f"{group}: git archive of source.path failed",
        )
    target.mkdir()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(target, filter="data")
    except tarfile.TarError as exc:
        raise CustomRoleError(
            f"{group}: source.path holds an entry the pull refuses to unpack: {exc}"
        ) from exc
    return f"{source.describe()} (commit {commit})"


def _check_local(
    group: str, source: Source, placements: list[Path], roles_dir: Path
) -> None:
    if not Path(source.url).is_dir():
        raise CustomRoleError(f"{group}: source.url {source.url} is not a directory")
    role = (Path(source.url) / source.path).resolve()
    for placement in placements:
        resolved = placement.resolve()
        if role == resolved or role.is_relative_to(resolved):
            raise CustomRoleError(
                f"{group}: local source {role} lies in the placement directory {placement} under {roles_dir}; a pull never deletes its own source"
            )


def _git(cwd: str | None, arguments: list[str], failure: str) -> bytes:
    # Exception: a git hook exports GIT_DIR, GIT_INDEX_FILE and friends, which
    # would point the scratch repository at the core checkout; the askpass
    # helpers and the detached session keep a fetch that needs credentials
    # from prompting.
    env = {key: value for key, value in os.environ.items() if key not in _DROPPED_ENV}
    env.update(GIT_TERMINAL_PROMPT="0", SSH_ASKPASS_REQUIRE="never")
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        start_new_session=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise CustomRoleError(f"{failure}: {detail}")
    return result.stdout
