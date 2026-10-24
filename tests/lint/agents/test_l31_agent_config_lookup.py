"""L31: no code reads agent.yml or cron.yml directly; every consumer goes
through lookup('agent_config', ...). Only the lookup itself may name them."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import PROJECT_ROOT
from utils.cache.files import read_text

SCAN_DIRS = ("agents", "plugins", "cli")
ALLOW = (
    PROJECT_ROOT / "plugins" / "lookup" / "agent_config.py",
)
NEEDLES = ("agent.yml", "cron.yml")


def _offending_files(root: Path) -> list[str]:
    offenders: list[str] = []
    for scan in SCAN_DIRS:
        base = root / scan
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if path in ALLOW:
                continue
            text = read_text(str(path))
            if any(needle in text for needle in NEEDLES):
                offenders.append(str(path.relative_to(root)))
    return offenders


def check(root: Path) -> list[str]:
    return sorted(_offending_files(root))


class TestL31(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(PROJECT_ROOT), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            consumer = Path(tmp) / "cli"
            consumer.mkdir()
            (consumer / "reader.py").write_text(
                "open('agent.yml').read()\n", encoding="utf-8"
            )
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
