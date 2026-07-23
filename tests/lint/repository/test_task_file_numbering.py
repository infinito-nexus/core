"""Lint: numbered task files in ``roles/*/tasks/`` follow one scheme.

Rules, applied per directory (``tasks/`` itself and every subdirectory):

* a task file starting with a digit must start with exactly TWO digits
  followed by ``_`` -- no letter suffixes (``02a_x.yml``); children of a
  numbered task belong in a subdirectory named after it instead,
* ``00_`` is reserved for ``00_core.yml``, and a numbered ``*_core.yml``
  must be exactly ``00_core.yml`` -- core is the entry stage and sits
  before everything else,
* the two-digit prefixes in one directory must be unique and consecutive
  -- no duplicated and no skipped numbers,
* the sequence starts at ``01`` (``00`` when the directory ships a
  ``00_core.yml``),
* within one task file, includes of numbered task files must appear in
  ascending numeric order -- a higher number called before a lower one
  hides the real execution order. Helpers shared across tasks belong in
  the role's ``tasks/utils/`` (unnumbered) instead of the numbered chain.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_ROLES = PROJECT_ROOT / "roles"

_NUMBERED_RE = re.compile(r"^(\d{2})_")
_DIGIT_START_RE = re.compile(r"^\d")
_INCLUDE_RE = re.compile(r"(?:include_tasks|import_tasks):\s*[\"']?([^\s\"'{]+\.yml)")


def _task_files_by_dir() -> dict[Path, list[Path]]:
    by_dir: dict[Path, list[Path]] = {}
    for path in iter_project_files(extensions=(".yml",)):
        p = Path(path)
        try:
            rel = p.relative_to(_ROLES)
        except ValueError:
            continue
        if len(rel.parts) < 3 or rel.parts[1] != "tasks":
            continue
        by_dir.setdefault(p.parent, []).append(p)
    return {d: sorted(files) for d, files in sorted(by_dir.items())}


def find_violations(directory: Path, files: list[Path]) -> list[str]:
    rel_dir = directory.relative_to(_ROLES).as_posix()
    violations: list[str] = []
    prefixes: list[int] = []
    names = {f.name for f in files}
    for entry in files:
        if not _DIGIT_START_RE.match(entry.name):
            continue
        match = _NUMBERED_RE.match(entry.name)
        if match is None:
            violations.append(
                f"{rel_dir}/{entry.name}: numbered task files must start with"
                " exactly two digits followed by '_'"
            )
            continue
        prefix = match.group(1)
        if prefix == "00" and entry.name != "00_core.yml":
            violations.append(
                f"{rel_dir}/{entry.name}: the 00_ prefix is reserved for 00_core.yml"
            )
        if entry.name.endswith("_core.yml") and entry.name != "00_core.yml":
            violations.append(
                f"{rel_dir}/{entry.name}: a numbered *_core.yml must be 00_core.yml"
            )
        prefixes.append(int(prefix))

    unique = sorted(set(prefixes))
    if len(unique) != len(prefixes):
        seen: set[int] = set()
        dupes = sorted({n for n in prefixes if n in seen or seen.add(n)})
        violations.append(f"{rel_dir}: duplicated task numbers {dupes}")
    if unique and unique[-1] - unique[0] + 1 != len(unique):
        expected = set(range(unique[0], unique[-1] + 1))
        violations.append(
            f"{rel_dir}: skipped task numbers {sorted(expected - set(unique))}"
        )
    start = 0 if "00_core.yml" in names else 1
    if unique and unique[0] > start:
        violations.append(
            f"{rel_dir}: numbering starts at {unique[0]:02d}, expected {start:02d}"
        )
    return violations


def find_order_violations(path: Path) -> list[str]:
    rel = path.relative_to(_ROLES).as_posix()
    violations: list[str] = []
    last: tuple[int, str] | None = None
    for ref in _INCLUDE_RE.findall(read_text(str(path))):
        match = _NUMBERED_RE.match(ref.rsplit("/", 1)[-1])
        if match is None:
            continue
        num = int(match.group(1))
        if last is not None and num < last[0]:
            violations.append(
                f"{rel}: includes {ref} after {last[1]} -- numbered includes"
                " must appear in ascending order"
            )
        last = (num, ref)
    return violations


class TestTaskFileNumbering(unittest.TestCase):
    def test_task_files_are_numbered_consistently(self) -> None:
        offenders: list[str] = []
        for directory, files in _task_files_by_dir().items():
            offenders.extend(find_violations(directory, files))
        if offenders:
            self.fail(
                f"{len(offenders)} task-numbering violation(s); rename the files"
                " (two leading digits, no letter suffixes, no gaps or duplicates,"
                " numbering starts at 01, 00_ only as 00_core.yml). Children of a"
                " numbered task belong in a subdirectory named after it; shared"
                " helpers belong in tasks/utils/:\n"
                + "\n".join(f"  {o}" for o in sorted(offenders))
            )

    def test_numbered_includes_stay_in_ascending_order(self) -> None:
        offenders: list[str] = []
        for files in _task_files_by_dir().values():
            for path in files:
                offenders.extend(find_order_violations(path))
        if offenders:
            self.fail(
                f"{len(offenders)} include-order violation(s); a task file must"
                " call numbered task files in ascending order:\n"
                + "\n".join(f"  {o}" for o in sorted(offenders))
            )


if __name__ == "__main__":
    unittest.main()
