from __future__ import annotations

import re
import unittest

from tests.lint.repository.documentation import PROJECT_ROOT
from utils.cache.files import read_text

MAKEFILE = PROJECT_ROOT / "Makefile"
TARGET_RE = re.compile(r"^([a-z][a-z0-9-]*):")
NAMED_TARGETS = (
    "test-runner-status",
    "build-cleanup",
    "runner-cleanup-report",
    "cache-evict",
    "runner-status",
    "runner-release",
    "runner-count",
    "test-runner-down",
)
UNKNOWN_TARGET = "no-such-target"


def _targets() -> set[str]:
    return {
        match.group(1)
        for line in read_text(str(MAKEFILE)).splitlines()
        if (match := TARGET_RE.match(line))
    }


class TestNamedTargetsExist(unittest.TestCase):
    def test_every_target_the_skills_name_exists(self) -> None:
        self.assertEqual(sorted(set(NAMED_TARGETS) - _targets()), [])

    def test_an_unknown_target_is_flagged(self) -> None:  # nocheck: test.text-presence -- negative control of the Makefile target parser above  # fmt: skip
        self.assertEqual(
            sorted({UNKNOWN_TARGET, *NAMED_TARGETS} - _targets()),
            [UNKNOWN_TARGET],
        )


if __name__ == "__main__":
    unittest.main()
