import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NESTED_CHECKOUTS = (".claude/worktrees/", ".worktrees/")


class TestDockerignore(unittest.TestCase):
    def test_dockerignore_is_the_gitignore(self) -> None:
        self.assertEqual(
            (PROJECT_ROOT / ".gitignore").read_text(),
            (PROJECT_ROOT / ".dockerignore").read_text(),
            "Run 'make fix-dockerignore': .dockerignore must be a copy of .gitignore.",
        )

    def test_nested_checkouts_stay_out_of_the_build_context(self) -> None:
        lines = (PROJECT_ROOT / ".dockerignore").read_text().splitlines()
        for entry in NESTED_CHECKOUTS:
            with self.subTest(entry=entry):
                self.assertIn(entry, lines)

    def test_compose_up_regenerates_the_dockerignore(self) -> None:
        makefile = (PROJECT_ROOT / "Makefile").read_text()
        match = re.search(r"^compose-up:(.*)$", makefile, re.MULTILINE)
        self.assertIsNotNone(match, "Makefile has no compose-up target")
        self.assertIn("fix-dockerignore", match.group(1).split())


if __name__ == "__main__":
    unittest.main()
