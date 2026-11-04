"""L17: only a designated model node calls the gateway; a routine module does
not import a model or gateway client, so a deterministic step cannot quietly
reach a model. The model call is made by the orchestrator at a model node, not
inside the routine's own code."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR
from utils.cache.files import read_text

ROUTINES = AGENTS_DIR / "routines"
GATEWAY = re.compile(
    r"(?:import|from)\s+(?:litellm|openai|anthropic|langchain_\w+|agents\.gateway)\b"
)


def check(routines_dir: Path) -> list[str]:
    problems: list[str] = []
    if not routines_dir.is_dir():
        return problems
    for path in sorted(routines_dir.rglob("*.py")):  # nocheck: project-walk
        if GATEWAY.search(read_text(str(path))):
            problems.append(f"{path.name}: a routine imports a model or gateway client")  # noqa: PERF401
    return problems


class TestL17(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROUTINES), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.py").write_text("import litellm\n", encoding="utf-8")
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
