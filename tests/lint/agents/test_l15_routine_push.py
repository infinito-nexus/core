"""L15: a routine step that pushes names its remote and its ref explicitly,
never relying on remote.pushDefault or push.default. A push label that
mentions no remote, or no ref (a ``<placeholder>`` branch, ``HEAD`` or a
``refs/`` path), is flagged."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR
from utils.cache.files import read_text

ROUTINES = AGENTS_DIR / "routines"
STEP_LABEL = re.compile(r'Step\([^,]+,\s*"([^"]*)"')
REMOTES = ("origin", "fork", "upstream")
REF = re.compile(r"<[a-z-]+>|\bHEAD\b|\brefs/")


def label_problems(label: str) -> list[str]:
    """Return what a push label leaves implicit.

    Args:
        label: the step label; one without ``push`` passes.
    """
    if "push" not in label.lower():
        return []
    problems = [] if any(rem in label for rem in REMOTES) else ["no remote"]
    if not REF.search(label):
        problems.append("no ref")
    return problems


def check(routines_dir: Path) -> list[str]:
    problems: list[str] = []
    if not routines_dir.is_dir():
        return problems
    for path in sorted(routines_dir.rglob("*.py")):  # nocheck: project-walk
        for label in STEP_LABEL.findall(read_text(str(path))):
            problems.extend(
                f"{path.name}: push step names {missing}: {label!r}"
                for missing in label_problems(label)
            )
    return problems


class TestL15(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(ROUTINES), [])

    def test_a_push_naming_remote_and_ref_passes(self):
        self.assertEqual(label_problems("git push -u origin <branch>"), [])
        self.assertEqual(label_problems("git push fork HEAD:refs/heads/x"), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.py").write_text(
                'from x import Step\nSTEPS=[Step("p", "git push the branch", "terminal")]\n',
                encoding="utf-8",
            )
            self.assertNotEqual(check(Path(tmp)), [])
        self.assertEqual(label_problems("push to own fork"), ["no ref"])
        self.assertEqual(label_problems("git push <branch>"), ["no remote"])


if __name__ == "__main__":
    unittest.main()
