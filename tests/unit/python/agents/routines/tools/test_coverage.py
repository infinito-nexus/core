"""Unit test: every shared deterministic tool node under agents/routines/tools/
has its own unit test module here."""

from __future__ import annotations

import unittest
from pathlib import Path

from agents.routines import tools

TOOLS = Path(tools.__file__).parent
TESTS = Path(__file__).parent


def untested(tool_dir: Path, test_dir: Path) -> list[str]:
    """Return every tool module without a ``test_<module>.py``.

    Args:
        tool_dir: the directory of tool modules.
        test_dir: the directory of their unit tests.
    """
    return [
        path.name
        for path in sorted(tool_dir.glob("*.py"))
        if path.name != "__init__.py" and not (test_dir / f"test_{path.name}").is_file()
    ]


class TestToolCoverage(unittest.TestCase):
    def test_every_tool_has_a_test(self) -> None:
        self.assertEqual(untested(TOOLS, TESTS), [])

    def test_a_tool_without_a_test_is_named(self) -> None:
        self.assertIn("retry.py", untested(TOOLS, TOOLS))


if __name__ == "__main__":
    unittest.main()
