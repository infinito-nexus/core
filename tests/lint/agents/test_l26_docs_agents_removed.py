"""L26: the removed agent-docs tree is gone, no live file points into it, and
every former action page resolves to its routine, skill or the agents README as
the requirement's mapping table states.

The walk for live references runs once with the other removal guards in
``tests/lint/ansible/variables/test_removed_names.py`` (``DocsAgents``).

SELF-EXPIRING: from 2027-02-18 it fails with a reminder to delete it.
"""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR, PROJECT_ROOT
from tests.lint.ansible.variables.test_removed_names import DocsAgents
from utils.cache.files import read_text

_ACTION_TO_ROUTINE = (
    "commit",
    "pull_request",
    "push_trigger_pull",
    "requirements",
    "testing",
    "verify_parallel",
    "design",
    "develop",
    "debug/ci",
    "debug/local",
    "debug/log",
    "iterate/compose",
    "iterate/playwright",
    "iterate/roundtrip",
    "iterate/runner",
    "iterate/swarm",
    "iterate/workflow",
)
_ACTION_TO_SKILL = ("i8-ci-trigger-priority", "i8-refactor")


def _mapping_problems(agents_dir: Path) -> list[str]:
    problems = [
        f"routine destination missing for action page: {name}"
        for name in _ACTION_TO_ROUTINE
        if not (agents_dir / "routines" / f"{name}.py").is_file()
    ]
    problems.extend(
        f"skill destination missing for action page: {name}"
        for name in _ACTION_TO_SKILL
        if not (agents_dir / "skills" / name / "SKILL.md").is_file()
    )
    if not (agents_dir / "README.md").is_file():
        problems.append("agents/README.md index destination missing")
    return problems


class TestL26(unittest.TestCase):
    def setUp(self) -> None:
        if DocsAgents.expired(dt.datetime.now(tz=dt.UTC).date()):
            self.fail(
                f"Removal guard expired (>= {DocsAgents.SUNSET.isoformat()}): "
                f"{DocsAgents.NEEDLE} is long gone. DELETE this guard test file, "
                "DocsAgents in tests/lint/ansible/variables/test_removed_names.py "
                "and its line in agents/criteria.yml."
            )

    def test_expiry_fires_on_the_sunset_date(self):
        self.assertFalse(DocsAgents.expired(DocsAgents.SUNSET - dt.timedelta(days=1)))
        self.assertTrue(DocsAgents.expired(DocsAgents.SUNSET))

    def test_tree_removed_and_action_pages_mapped(self):
        problems: list[str] = []
        if (PROJECT_ROOT / "docs" / "agents").exists():
            problems.append(f"{DocsAgents.NEEDLE} still exists")
        problems.extend(_mapping_problems(AGENTS_DIR))
        self.assertEqual(problems, [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "agents").mkdir(parents=True)
            (root / "page.md").write_text(
                "see docs/" + "agents/action/commit.md\n", encoding="utf-8"
            )
            items = [
                (path.relative_to(root).as_posix(), read_text(str(path)))
                for path in sorted(root.rglob("*.md"))  # nocheck: project-walk
            ]
            self.assertNotEqual(DocsAgents.reference_problems(items), [])
            self.assertTrue((root / "docs" / "agents").exists())


if __name__ == "__main__":
    unittest.main()
