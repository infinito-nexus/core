"""Self-expiring removal guard: nothing names the container hard repair again.

``sys-ctl-rpr-container-hard`` ran ``compose down`` and ``up -d`` on every
instance below ``DIR_COMPOSITIONS`` each Sunday, so every application went down
once a week and running CI jobs died with it. ``sys-ctl-rpr-container-soft``
restarts a project once one of its containers is unhealthy or exited, so the
role, its units and its service, schedule and timeout variables are gone. A
branch from before the removal brings the weekly restart back, and a leftover
``roles/`` directory puts its unit back into ``SYS_SERVICE_GROUP_REPAIR``; this
guard fails on both instead. The retirement in ``sys-svc-compose`` keeps the
role id on its one ``COMPOSE_RETIRED_SERVICE_ID`` line, and its test spells the
unit names out. ``locale/`` is skipped, because the i18n extraction regenerates
it, and so are the release notes, which list a removed role under "Removed".

SELF-EXPIRING: from 2027-02-05 it fails with a reminder to delete it together
with the retirement.
"""

from __future__ import annotations

import datetime as dt
import re
import unittest
from pathlib import Path

from utils.cache.files import iter_non_ignored_files, read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = "sys-ctl-rpr-container-hard"
NAMES = (
    "rpr-container-hard",
    "rpr_container_hard",
    "SYS_SERVICE_REPAIR_CONTAINER_HARD",
    "SYS_SCHEDULE_REPAIR_DOCKER_HARD",
    "SYS_TIMEOUT_CONTAINER_RPR_HARD",
)
SUNSET = dt.date(2027, 2, 5)
SKIPPED_PREFIX = "locale/"
RELEASE_NOTES = frozenset(
    {
        "CHANGELOG.md",
        "packaging/debian/changelog",
        "packaging/fedora/infinito-nexus.spec",
    }
)
RETIREMENT_VARS = f"roles/sys-svc-compose/{ROLE_FILE_VARS_MAIN}"
RETIREMENT_KEY = "COMPOSE_RETIRED_SERVICE_ID:"
RETIREMENT_TEST = "tests/unit/python/roles/sys-svc-compose/test_retire.py"
_NAME_RE = re.compile("|".join(re.escape(name) for name in NAMES))
_SELF = Path(__file__).resolve()


def expired(today: dt.date) -> bool:
    return today >= SUNSET


def skipped(rel: str) -> bool:
    """Whether the guard leaves the file at *rel* unread.

    Args:
        rel: the file's path relative to the project root.
    """
    return (
        rel.startswith(SKIPPED_PREFIX) or rel in RELEASE_NOTES or rel == RETIREMENT_TEST
    )


def _scanned() -> list[tuple[str, str]]:
    files = []
    for path in iter_non_ignored_files():
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if skipped(rel) or Path(path).resolve() == _SELF:
            continue
        try:
            files.append((rel, read_text(path)))
        except (OSError, UnicodeDecodeError):
            continue
    return files


def named(rel: str, text: str) -> list[tuple[int, str]]:
    """Line numbers and removed names that *text* carries outside the retirement.

    Args:
        rel: the file's path relative to the project root.
        text: the file's content.
    """
    return [
        (number, match.group(0))
        for number, line in enumerate(text.splitlines(), start=1)
        if not (rel == RETIREMENT_VARS and line.startswith(RETIREMENT_KEY))
        for match in _NAME_RE.finditer(line)
    ]


def findings(rel: str, text: str) -> list[tuple[int, str]]:
    """Line numbers and removed names the guard reports for the file at *rel*.

    Args:
        rel: the file's path relative to the project root.
        text: the file's content.
    """
    return [] if skipped(rel) else named(rel, text)


class TestRprContainerHardRemoved(unittest.TestCase):
    def setUp(self) -> None:
        if expired(dt.datetime.now(tz=dt.UTC).date()):
            self.fail(
                f"Removal guard expired (>= {SUNSET.isoformat()}): {ROLE} is long "
                "gone. DELETE this guard, its negative controls, and the "
                "retirement in roles/sys-svc-compose (tasks/retire.yml, its "
                "include in tasks/00_core.yml, the COMPOSE_RETIRED_* vars and "
                f"{RETIREMENT_TEST})."
            )

    def test_the_role_directory_is_gone(self) -> None:
        self.assertFalse(
            (PROJECT_ROOT / "roles" / ROLE).exists(),
            f"roles/{ROLE} exists, so get_category_entries puts its unit back "
            "into SYS_SERVICE_GROUP_REPAIR and every lock list",
        )

    def test_no_file_names_the_hard_repair(self) -> None:
        found = [
            f"{rel}:{line}: {name}"
            for rel, content in _scanned()
            for line, name in findings(rel, content)
        ]
        self.assertEqual(
            found,
            [],
            f"{ROLE} was removed: its weekly compose down and up took every "
            "application down, and sys-ctl-rpr-container-soft restarts a "
            "project with an unhealthy or exited container instead:\n"
            + "\n".join(found),
        )


if __name__ == "__main__":
    unittest.main()
