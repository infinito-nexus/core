import io
import unittest
from unittest.mock import patch

from cli.console import ls
from cli.console.constants import LS_DESC_LIMIT


class TestTruncate(unittest.TestCase):
    def test_short_passthrough(self):
        self.assertEqual(ls.truncate("short", 30), "short")

    def test_exact_limit_passthrough(self):
        text = "x" * 30
        self.assertEqual(ls.truncate(text, 30), text)

    def test_over_limit_uses_ellipsis(self):
        text = "x" * 50
        out = ls.truncate(text, 30)
        self.assertEqual(len(out), 30)
        self.assertTrue(out.endswith("…"))


class TestDoLs(unittest.TestCase):
    def test_lists_root_categories(self):
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            ls.do_ls([])
        text = out.getvalue()
        self.assertIn("administration", text)
        self.assertIn("meta", text)

    def test_entries_get_emoji_prefix(self):
        from cli.core.help import _COMMAND_EMOJI, _FOLDER_EMOJI

        with patch("sys.stdout", new_callable=io.StringIO) as out:
            ls.do_ls([])
        text = out.getvalue()
        self.assertIn(_FOLDER_EMOJI, text)
        self.assertIn(_COMMAND_EMOJI, text)

    def test_folders_listed_before_apps(self):
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            ls.do_ls([])
        lines = [line for line in out.getvalue().splitlines() if line.strip()]
        admin_idx = next(i for i, line in enumerate(lines) if "administration" in line)
        console_idx = next(i for i, line in enumerate(lines) if "console" in line)
        self.assertLess(admin_idx, console_idx)

    def test_truncates_description_to_30_chars(self):
        with patch("sys.stdout", new_callable=io.StringIO) as out:
            ls.do_ls([])
        for line in out.getvalue().splitlines():
            if not line.strip():
                continue
            visible = line.replace("\033[2m", "").replace("\033[0m", "")
            # Layout: `  <emoji>  <name>  <desc>`; desc is the segment
            # past the two-space separator following the padded name.
            parts = visible.split("  ")
            desc = parts[-1].strip()
            self.assertLessEqual(len(desc), LS_DESC_LIMIT)


if __name__ == "__main__":
    unittest.main()
