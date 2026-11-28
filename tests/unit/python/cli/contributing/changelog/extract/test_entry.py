import shutil
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from cli.contributing.changelog.extract.entry import CONFIG, insert, lint, linter
from utils.cache.files import PROJECT_ROOT

CHANGELOG = "# Changelog\n\n## [1.0.0] - 2026-01-01\n\n- Old\n"
ENTRY = "# Changelog\n\n## [1.1.0] - 2026-02-01\n\nAdded:\n\n- New\n"


class TestInsert(unittest.TestCase):
    def test_the_entry_goes_before_the_newest_release(self) -> None:
        self.assertEqual(
            insert(CHANGELOG, ENTRY),
            "# Changelog\n\n## [1.1.0] - 2026-02-01\n\nAdded:\n\n- New\n\n"
            "## [1.0.0] - 2026-01-01\n\n- Old\n",
        )

    def test_an_entry_without_a_release_header_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            insert(CHANGELOG, "Added:\n\n- New\n")


class TestLint(unittest.TestCase):
    def test_nothing_is_installed_when_no_linter_exists(self) -> None:
        with (
            mock.patch("shutil.which", return_value=None),
            self.assertRaises(FileNotFoundError),
        ):
            linter()

    @unittest.skipUnless(
        shutil.which("markdownlint-cli2"), "markdownlint-cli2 not installed"
    )
    def test_the_repository_rules_judge_the_scratch_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            target = scratch / "CHANGELOG.md"
            target.write_text(insert(CHANGELOG, ENTRY), encoding="utf-8")
            self.assertEqual(lint(scratch, PROJECT_ROOT / CONFIG).returncode, 0)
            target.write_text("# Changelog\n* star bullet\n", encoding="utf-8")
            self.assertNotEqual(lint(scratch, PROJECT_ROOT / CONFIG).returncode, 0)


if __name__ == "__main__":
    unittest.main()
