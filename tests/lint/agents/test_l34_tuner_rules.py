"""L34: the tuner's AGENTS.md names its trusted measurement sources, the
invalid-comparison cases, the never-traded properties, the measured
language-choice rule and the deterministic log scanner."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import ROLES_DIR

TUNER_AGENTS = ROLES_DIR / "tuner" / "AGENTS.md"
REQUIRED = (
    "profile_tasks",
    "per-target wall-clock",
    "FAILED TARGETS",
    "budget",
    "no_log",
    "concurrency",
    "lint intent",
    "cli.tune.logscan",
    "CPU-bound",
)


def check(agents_md: Path) -> list[str]:
    if not agents_md.is_file():
        return [f"{agents_md} missing"]
    text = agents_md.read_text(encoding="utf-8")
    return [f"tuner AGENTS.md does not name '{needle}'" for needle in REQUIRED if needle not in text]


class TestL34(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(TUNER_AGENTS), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            thin = Path(tmp) / "AGENTS.md"
            thin.write_text("# Tuner\n\n- be fast\n", encoding="utf-8")
            self.assertNotEqual(check(thin), [])


if __name__ == "__main__":
    unittest.main()
