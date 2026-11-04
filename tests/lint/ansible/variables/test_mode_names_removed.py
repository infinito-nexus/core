"""Self-expiring removal guard: no project file names a ``MODE_``-prefixed mode.

The modes of ``group_vars/all/01_modes.yml`` dropped their prefix, ``MODE_ASSERT``
became ``VALIDATE`` (CLI flag ``--validate``) and ``MODE_ASSERT_LOCAL`` is gone.
A branch from before the rename still sets or reads an old name, which Ansible
accepts in silence as an unrelated variable; this guard fails on it instead.
``locale/`` is skipped, because the i18n extraction regenerates it from the
documentation.

SELF-EXPIRING: from 2027-02-04 it fails with a reminder to delete it.
"""

from __future__ import annotations

import datetime as dt
import re
import unittest
from pathlib import Path

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

RENAMES: dict[str, str] = {
    "MODE_DUMMY": "DUMMY",
    "MODE_DEBUG": "DEBUG",
    "MODE_RESET": "RESET",
    "MODE_CLEANUP": "CLEANUP",
    "MODE_ASSERT": "VALIDATE",
    "MODE_ASSERT_LOCAL": "VALIDATE",
    "MODE_BACKUP": "BACKUP",
    "MODE_DEMO": "DEMO",
}
SUNSET = dt.date(2027, 2, 4)
SKIPPED_PREFIX = "locale/"
_NAME_RE = re.compile(rf"\b(?:{'|'.join(sorted(RENAMES, key=len, reverse=True))})\b")
_SELF = Path(__file__).resolve()


def expired(today: dt.date) -> bool:
    return today >= SUNSET


def _scanned() -> list[tuple[str, str]]:
    files = []
    for path in iter_non_ignored_files():
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if rel.startswith(SKIPPED_PREFIX) or Path(path).resolve() == _SELF:
            continue
        try:
            files.append((rel, read_text(path)))
        except (OSError, UnicodeDecodeError):
            continue
    return files


def named(text: str) -> list[tuple[int, str]]:
    """Line numbers and old names that *text* still carries.

    Args:
        text: the content of one project file.
    """
    return [
        (number, match.group(0))
        for number, line in enumerate(text.splitlines(), start=1)
        for match in _NAME_RE.finditer(line)
    ]


class TestModeNamesRemoved(unittest.TestCase):
    def test_no_file_names_an_old_mode(self) -> None:
        if expired(dt.datetime.now(tz=dt.UTC).date()):
            self.fail(
                f"Removal guard expired (>= {SUNSET.isoformat()}): the MODE_ names "
                "are long gone. DELETE this guard test file and its negative controls."
            )
        findings = [
            f"{rel}:{line}: {old} -> {RENAMES[old]}"
            for rel, content in _scanned()
            for line, old in named(content)
        ]
        self.assertEqual(
            findings,
            [],
            "The modes lost their MODE_ prefix: DUMMY, DEBUG, RESET, CLEANUP, "
            "VALIDATE (was MODE_ASSERT; CLI --validate), BACKUP, DEMO. Roles read "
            "DEBUG / VALIDATE through lookup('debug') / lookup('validate'):\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
