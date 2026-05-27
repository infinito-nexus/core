import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.files import read_text
from utils.github.profile import role_summary

SAMPLE_LOG = """\
PLAY RECAP **********************************************************************
host : ok=5 changed=2

Saturday 21 May 2026  10:00:00 +0000 (0:00:01.234)       0:01:23.456 ***********
===============================================================================
web-app-keycloak ------------------------------------------------------- 42.50s
sys-svc-mail ----------------------------------------------------------- 30.10s
web-app-keycloak ------------------------------------------------------- 12.40s
docker-compose ---------------------------------------------------------  8.00s
sys-svc-mail : Some task -----------------------------------------------  3.00s
total ------------------------------------------------------------------ 93.00s
"""


def _write_tempfile(content: str, suffix: str) -> str:
    fd, name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with Path(name).open("w", encoding="utf-8") as fh:
        fh.write(content)
    return name


class TestParseRoleTimes(unittest.TestCase):
    def _write(self, content: str) -> Path:
        name = _write_tempfile(content, ".log")
        self.addCleanup(os.unlink, name)
        return Path(name)

    def test_aggregates_duplicate_roles(self):
        path = self._write(SAMPLE_LOG)
        rows = role_summary.parse_role_times(path)
        names = [name for name, _ in rows]
        self.assertEqual(names[0], "web-app-keycloak")
        self.assertAlmostEqual(dict(rows)["web-app-keycloak"], 54.90)

    def test_excludes_total_line(self):
        path = self._write(SAMPLE_LOG)
        rows = role_summary.parse_role_times(path)
        self.assertNotIn("total", dict(rows))

    def test_excludes_task_entries_with_colon(self):
        path = self._write(SAMPLE_LOG)
        rows = role_summary.parse_role_times(path)
        for name, _ in rows:
            self.assertNotIn(" : ", name)

    def test_sorted_descending(self):
        path = self._write(SAMPLE_LOG)
        rows = role_summary.parse_role_times(path)
        durations = [seconds for _, seconds in rows]
        self.assertEqual(durations, sorted(durations, reverse=True))

    def test_strips_ansi_escape_codes(self):
        coloured = "\x1b[33mrole-x\x1b[0m ------------------------------ 5.00s\n"
        path = self._write(coloured)
        rows = role_summary.parse_role_times(path)
        self.assertEqual(rows, [("role-x", 5.00)])

    def test_empty_log_returns_empty_list(self):
        path = self._write("nothing here\n")
        rows = role_summary.parse_role_times(path)
        self.assertEqual(rows, [])

    def test_strips_ansible_log_prefix(self):
        prefixed = (
            "2026-05-22 15:23:23,180 p=985 u=root n=ansible INFO|"
            " web-app-keycloak ------------------------------------ 42.50s\n"
            "2026-05-22 15:23:24,000 p=985 u=root n=ansible INFO|"
            " sys-svc-mail : Some task ----------------------------  3.00s\n"
            "2026-05-22 15:23:25,000 p=985 u=root n=ansible INFO|"
            " total ----------------------------------------------- 93.00s\n"
        )
        path = self._write(prefixed)
        rows = role_summary.parse_role_times(path)
        names = [name for name, _ in rows]
        self.assertEqual(names, ["web-app-keycloak"])
        self.assertAlmostEqual(dict(rows)["web-app-keycloak"], 42.50)


class TestFormatTable(unittest.TestCase):
    def test_renders_markdown_table(self):
        rows = [("alpha", 10.5), ("beta", 7.25)]
        out = role_summary._format_table(rows)
        self.assertIn("| 1 | `alpha` | 10.50s |", out)
        self.assertIn("| 2 | `beta` | 7.25s |", out)
        self.assertIn("## ⏱️ Role runtimes", out)

    def test_renders_all_rows(self):
        rows = [("a", 5.0), ("b", 4.0), ("c", 3.0)]
        out = role_summary._format_table(rows)
        self.assertIn("`a`", out)
        self.assertIn("`b`", out)
        self.assertIn("`c`", out)


class TestMain(unittest.TestCase):
    def test_missing_log_returns_zero(self):
        rc = role_summary.main(["role_summary.py", "/nonexistent/path.log"])
        self.assertEqual(rc, 0)

    def test_missing_argument_returns_two(self):
        rc = role_summary.main(["role_summary.py"])
        self.assertEqual(rc, 2)

    def test_writes_to_step_summary(self):
        log_name = _write_tempfile(SAMPLE_LOG, ".log")
        self.addCleanup(os.unlink, log_name)
        sum_name = _write_tempfile("", ".md")
        self.addCleanup(os.unlink, sum_name)

        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": sum_name}):
            rc = role_summary.main(["role_summary.py", log_name])
        self.assertEqual(rc, 0)
        content = read_text(sum_name)
        self.assertIn("## ⏱️ Role runtimes", content)
        self.assertIn("web-app-keycloak", content)


if __name__ == "__main__":
    unittest.main()
