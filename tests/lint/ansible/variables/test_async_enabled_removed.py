"""Self-expiring removal guard: no project file names ``ASYNC_ENABLED``.

Every task that read the switch now runs async with ``ASYNC_TIME`` and
``ASYNC_POLL``, and the full-cycle deploy marks its second pass with
``DEPLOY_IS_UPDATE``. A branch from before the removal still sets or reads the
old name, which Ansible accepts in silence; this guard fails on it instead.
``locale/`` is skipped, because the i18n extraction regenerates it from the
documentation.

SELF-EXPIRING: from 2027-02-03 it fails with a reminder to delete it.
"""

from __future__ import annotations

import datetime as dt
import re
import unittest
from pathlib import Path

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

NAME = "ASYNC_ENABLED"
SUNSET = dt.date(2027, 2, 3)
SKIPPED_PREFIX = "locale/"
_NAME_RE = re.compile(rf"\b{NAME}\b")
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


def named_lines(text: str) -> list[int]:
    """Line numbers of *text* that name the removed switch.

    Args:
        text: the content of one project file.
    """
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if _NAME_RE.search(line)
    ]


class TestAsyncEnabledRemoved(unittest.TestCase):
    def test_no_file_names_async_enabled(self) -> None:
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
            f"{NAME} was removed: tasks run async unconditionally, a task that "
            "must run synchronously drops its async and poll (a sys-service caller "
            "sets system_service_force_linear_sync), and the full-cycle update pass "
            "is DEPLOY_IS_UPDATE:\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
