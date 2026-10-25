"""L26: the removed agent-docs tree is gone, no live file points into it, and
every former action page resolves to its routine, skill or the agents README as
the requirement's mapping table states."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR, PROJECT_ROOT
from utils.cache.files import iter_project_files_with_content, read_text

NEEDLE = "docs/" + "agents"

# Exception: the generated i18n catalogs and the requirement and changelog specs
# keep the old path in prose until re-extraction; they are not live links.
_EXEMPT_PREFIXES = (
    "docs/changelog/",
    "docs/requirements/",
    "locale/",
)

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


def _reference_problems(items) -> list[str]:
    """Return a problem per (relpath, content) pair that names the removed tree.

    Args:
        items: iterable of ``(repo-relative posix path, file content)``.
    """
    problems: list[str] = []
    for rel, content in items:
        if rel.startswith(_EXEMPT_PREFIXES):
            continue
        if NEEDLE in content:
            problems.append(f"{rel}: references the removed {NEEDLE} tree")
    return problems


def _real_reference_problems() -> list[str]:
    items = (
        (Path(path).relative_to(PROJECT_ROOT).as_posix(), content)
        for path, content in iter_project_files_with_content()
    )
    return _reference_problems(items)


def _mapping_problems(agents_dir: Path) -> list[str]:
    problems: list[str] = []
    for name in _ACTION_TO_ROUTINE:
        if not (agents_dir / "routines" / f"{name}.py").is_file():
            problems.append(f"routine destination missing for action page: {name}")
    for name in _ACTION_TO_SKILL:
        if not (agents_dir / "skills" / name / "SKILL.md").is_file():
            problems.append(f"skill destination missing for action page: {name}")
    if not (agents_dir / "README.md").is_file():
        problems.append("agents/README.md index destination missing")
    return problems


class TestL26(unittest.TestCase):
    def test_tree_removed_and_action_pages_mapped(self):
        problems: list[str] = []
        if (PROJECT_ROOT / "docs" / "agents").exists():
            problems.append(f"{NEEDLE} still exists")
        problems.extend(_mapping_problems(AGENTS_DIR))
        self.assertEqual(problems, [])

    def test_no_live_file_references_the_removed_tree(self):
        self.assertEqual(_real_reference_problems(), [])

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
            self.assertNotEqual(_reference_problems(items), [])
            self.assertTrue((root / "docs" / "agents").exists())


if __name__ == "__main__":
    unittest.main()
