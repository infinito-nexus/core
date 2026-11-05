import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

NESTED_CHECKOUTS = (".claude/worktrees/", ".worktrees/")


class TestDockerignore(unittest.TestCase):
    def test_dockerignore_is_the_gitignore(self) -> None:
        self.assertEqual(
            read_text(str(PROJECT_ROOT / ".gitignore")),
            read_text(str(PROJECT_ROOT / ".dockerignore")),
            "Run 'make fix-dockerignore': .dockerignore must be a copy of .gitignore.",
        )

    def test_nested_checkouts_stay_out_of_the_build_context(self) -> None:
        lines = read_text(str(PROJECT_ROOT / ".dockerignore")).splitlines()
        for entry in NESTED_CHECKOUTS:
            with self.subTest(entry=entry):
                self.assertIn(entry, lines)

    def test_compose_up_regenerates_the_dockerignore(self) -> None:
        makefile = read_text(str(PROJECT_ROOT / "Makefile"))
        match = re.search(r"^compose-up:(.*)$", makefile, re.MULTILINE)
        self.assertIsNotNone(match, "Makefile has no compose-up target")
        self.assertIn("fix-dockerignore", match.group(1).split())


if __name__ == "__main__":
    unittest.main()
