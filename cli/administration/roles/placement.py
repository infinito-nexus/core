"""Place the custom roles an inventory declares under ``roles/`` and remove them again.

A pull stages every declared role in a work directory outside ``roles/``
and checks it before the first entry of ``roles/`` changes, so a refused
pull leaves ``roles/`` as it was. A pull or clean only ever replaces or
removes the directories the pull placed itself, whose marker names them.

Both hold an exclusive lock under the work directory, so two of them on
one checkout never interleave, and clear what an interrupted run left
there. They swap entries by rename and delete the old copies only after
the swap, so an interrupt never leaves a declared role missing.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from yaml import YAMLError

from utils.cache.yaml import load_yaml_tagged
from utils.roles.custom import CustomRoleError
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_VARS_MAIN

from .declaration import read_declarations
from .inventory import is_host_list
from .marker import MARKER_FILE, custom_entries, is_placed, write_marker
from .source import check, stage

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .declaration import Source

LOCK_FILE = ".lock"
_LEFT = "left in place, the pull did not place it"


def pull(inventory: Path, roles_dir: Path, work_dir: Path) -> list[str]:
    """Place the custom roles *inventory* declares and remove the ones it dropped.

    Args:
        inventory: the inventory file or directory; an inline host list
            such as ``localhost,`` declares nothing and changes nothing.
        roles_dir: the ``roles/`` of the core checkout that runs the deploy.
        work_dir: staging directory outside ``roles_dir`` on its filesystem.

    Returns:
        One line per placed or removed role, naming its source and
        resolved commit, and one per ``roles/web-app-cst-*`` entry the
        pull left alone.

    Raises:
        CustomRoleError: naming the group, or the file, that stops the run.
    """
    if is_host_list(inventory):
        return []
    if not inventory.exists():
        raise CustomRoleError(
            f"inventory {inventory} is neither a file nor a directory"
        )
    declared, errors = read_declarations(inventory, roles_dir)
    if errors:
        raise CustomRoleError("\n".join(errors))
    if not declared and not custom_entries(roles_dir):
        return []
    with _locked(work_dir):
        return _place(declared, roles_dir, work_dir)


def clean(roles_dir: Path, work_dir: Path) -> list[str]:
    """Remove every ``roles/web-app-cst-*`` directory the pull placed and nothing else.

    Args:
        roles_dir: the role search directory.
        work_dir: staging directory outside ``roles_dir`` on its filesystem.

    Returns:
        One line per ``roles/web-app-cst-*`` entry: removed, or left in
        place because the pull did not place it.
    """
    with _locked(work_dir):
        entries = custom_entries(roles_dir)
        placed = [entry for entry in entries if is_placed(entry)]
        holders: list[Path] = []
        try:
            _rename_all(
                [(entry, _retired(entry, work_dir, holders)) for entry in placed]
            )
        finally:
            _discard(holders)
    return [
        f"{entry.name}: removed" if entry in placed else f"{entry.name}: {_LEFT}"
        for entry in entries
    ]


def _place(declared: dict[str, Source], roles_dir: Path, work_dir: Path) -> list[str]:
    entries = custom_entries(roles_dir)
    for group, source in sorted(declared.items()):
        check(group, source, entries, roles_dir)
        _check_target(roles_dir / group)
    undeclared = [entry for entry in entries if entry.name not in declared]
    lines: list[str] = []
    staged: list[tuple[Path, Path]] = []
    holders: list[Path] = []
    try:
        for group, source in sorted(declared.items()):
            staging = _holder(work_dir, group, holders) / group
            origin = stage(group, source, staging)
            _check_role(group, staging)
            write_marker(staging, group, origin)
            staged.append((staging, roles_dir / group))
            lines.append(f"{group}: {origin}")
        for _staging, target in staged:
            _check_target(target)
        dropped = [entry for entry in undeclared if is_placed(entry)]
        moves = [(entry, _retired(entry, work_dir, holders)) for entry in dropped]
        for staging, target in staged:
            if os.path.lexists(target):
                moves.append((target, _retired(target, work_dir, holders)))
            moves.append((staging, target))
        _rename_all(moves)
    finally:
        _discard(holders)
    lines.extend(
        f"{entry.name}: removed, the inventory no longer declares it"
        if entry in dropped
        else f"{entry.name}: {_LEFT}"
        for entry in undeclared
    )
    return sorted(lines)


def _check_target(target: Path) -> None:
    if target.is_symlink():
        raise CustomRoleError(
            f"{target.name}: {target} is a symbolic link to {target.readlink()}, "
            f"not a role the pull placed; remove the link (rm {target}) and pull again"
        )
    if target.exists() and not is_placed(target):
        raise CustomRoleError(
            f"{target.name}: {target} was not placed by a pull (its {MARKER_FILE} "
            "does not name it); the pull never replaces it, remove it by hand"
        )


def _check_role(group: str, staged: Path) -> None:
    if (staged / MARKER_FILE).is_symlink():
        raise CustomRoleError(
            f"{group}: source.path {MARKER_FILE} is a symbolic link; the pull "
            "refuses a source that could redirect the marker it writes"
        )
    if not (staged / ROLE_FILE_META_MAIN).is_file():
        raise CustomRoleError(
            f"{group}: source.path holds no {ROLE_FILE_META_MAIN}, so it is no role directory"
        )
    variables = staged / ROLE_FILE_VARS_MAIN
    try:
        data = load_yaml_tagged(variables) if variables.is_file() else None
    except (ValueError, YAMLError) as exc:
        raise CustomRoleError(
            f"{group}: {ROLE_FILE_VARS_MAIN} cannot be read: {exc}"
        ) from exc
    application_id = data.get("application_id") if isinstance(data, dict) else None
    if application_id != group:
        raise CustomRoleError(
            f"{group}: {ROLE_FILE_VARS_MAIN} application_id is {application_id!r}, but the group is '{group}'; core never renames a role"
        )


@contextlib.contextmanager
def _locked(work_dir: Path) -> Iterator[None]:
    work_dir.mkdir(parents=True, exist_ok=True)
    lock = work_dir / LOCK_FILE
    descriptor = os.open(lock, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                f"[INFO] waiting for another custom-role pull or clean of this checkout ({lock})",
                file=sys.stderr,
                flush=True,
            )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        _discard([entry for entry in work_dir.iterdir() if entry.name != LOCK_FILE])
        yield
    finally:
        os.close(descriptor)


def _holder(work_dir: Path, prefix: str, holders: list[Path]) -> Path:
    holder = Path(tempfile.mkdtemp(prefix=f"{prefix}.", dir=work_dir))
    holders.append(holder)
    return holder


def _retired(entry: Path, work_dir: Path, holders: list[Path]) -> Path:
    return _holder(work_dir, f"{entry.name}.retired", holders) / entry.name


def _rename_all(moves: list[tuple[Path, Path]]) -> None:
    done: list[tuple[Path, Path]] = []
    try:
        for old, new in moves:
            old.rename(new)
            done.append((old, new))
    except BaseException:
        for old, new in reversed(done):
            new.rename(old)
        raise


def _discard(entries: list[Path]) -> None:
    for entry in entries:
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError as exc:
            print(
                f"[WARN] cannot remove {entry} ({exc}); container-owned leftovers "
                "go with make clean-container-owned",
                file=sys.stderr,
            )
