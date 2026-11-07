"""Self-expiring removal guard: no project file names ``TOR_EGRESS_ROUTER_ENABLED``.

``services.tor.egress.route`` (``none``, ``onion``, ``all``) replaced the
boolean ``services.tor.egress.enabled``, and ``TOR_EGRESS_ROUTE`` replaced the
variable that read it. The removed key is refused at deploy time and by the
``tor.egress`` lint, but a branch from before the migration that still reads
the removed variable gets an undefined variable only when its task runs; this
guard fails on it instead. ``locale/`` is skipped, because the i18n extraction
regenerates it from the documentation, and so are the requirement documents,
which record the migration under the old names.

SELF-EXPIRING: from 2027-02-06 it fails with a reminder to delete it.
"""

from __future__ import annotations

import datetime as dt
import re
import unittest
from pathlib import Path

from utils.cache.files import iter_non_ignored_files, read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

NAME = "TOR_EGRESS_ROUTER_ENABLED"
SUNSET = dt.date(2027, 2, 6)
SKIPPED_PREFIXES = ("locale/", "docs/requirements/")
_NAME_RE = re.compile(rf"\b{NAME}\b")
_SELF = Path(__file__).resolve()


def expired(today: dt.date) -> bool:
    return today >= SUNSET


def skipped(rel: str) -> bool:
    """Whether the guard leaves the file at *rel* unread.

    Args:
        rel: the file's path relative to the project root.
    """
    return rel.startswith(SKIPPED_PREFIXES)


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


def named_lines(text: str) -> list[int]:
    """Line numbers of *text* that name the removed variable.

    Args:
        text: the content of one project file.
    """
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if _NAME_RE.search(line)
    ]


class TestTorEgressRouterEnabledRemoved(unittest.TestCase):
    def test_no_file_names_the_removed_variable(self) -> None:
        if expired(dt.datetime.now(tz=dt.UTC).date()):
            self.fail(
                f"Removal guard expired (>= {SUNSET.isoformat()}): {NAME} is long "
                "gone. DELETE this guard test file and its negative controls."
            )
        findings = [
            f"{rel}:{line}"
            for rel, content in _scanned()
            for line in named_lines(content)
        ]
        self.assertEqual(
            findings,
            [],
            f"{NAME} was removed: read the route from TOR_EGRESS_ROUTE "
            "(services.tor.egress.route: none, onion or all) instead:\n"
            + "\n".join(findings),
        )

    def test_a_line_naming_the_removed_variable_is_reported(self) -> None:
        text = "\n".join(
            (
                "TOR_EGRESS_ROUTE: onion",
                f"when: {NAME} | bool",
                f"X{NAME}",
            )
        )
        self.assertEqual(named_lines(text), [2])

    def test_the_requirement_history_and_the_catalogs_are_skipped(self) -> None:
        self.assertTrue(skipped("docs/requirements/history.md"))
        self.assertTrue(skipped("locale/de/LC_MESSAGES/docs.po"))
        self.assertFalse(skipped(f"roles/svc-net-tor/{ROLE_FILE_VARS_MAIN}"))

    def test_expiry_fires_on_the_sunset_date(self) -> None:
        self.assertFalse(expired(SUNSET - dt.timedelta(days=1)))
        self.assertTrue(expired(SUNSET))


if __name__ == "__main__":
    unittest.main()
