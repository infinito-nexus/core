"""L13: no hardcoded runtime list in svc-ai-agent-broker or
svc-ai-agent-orchestrator. The runtimes come from the declared platform data,
never from a runtime name written into the code."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import PROJECT_ROOT
from utils.cache.files import read_text

ROLE_PYTHON = (
    PROJECT_ROOT / "roles" / "svc-ai-agent-broker" / "files" / "python",
    PROJECT_ROOT / "roles" / "svc-ai-agent-orchestrator" / "files" / "python",
)
RUNTIME_NAME = re.compile(r"""['"](?:hermes|openclaw|claude-code)['"]""")


def check(dirs) -> list[str]:
    problems: list[str] = []
    for base in dirs:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):  # nocheck: project-walk
            for number, line in enumerate(read_text(str(path)).splitlines(), 1):
                if RUNTIME_NAME.search(line):
                    problems.append(f"{path.name}:{number}: hardcoded runtime name")
    return problems


class TestL13(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROLE_PYTHON), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "agents.py").write_text(
                'CONFIG_RENDERERS = {"hermes": h, "openclaw": o}\n', encoding="utf-8"
            )
            self.assertNotEqual(check((base,)), [])


if __name__ == "__main__":
    unittest.main()
