"""Unit tests for :mod:`utils.github.playwright_summary`.

Synthetic JUnit XML fixtures are produced under a tempdir so the real
project tree is never touched. Coverage spans the small pure helpers
(``_first_line``, ``_md_escape_cell``), the parser (``_extract_records``,
``_summarize_file``), the renderer (``_render``), and the CLI entry
point (``main``), including the three early-exit branches for missing
directories / no junit files / unparseable junit files.
"""

from __future__ import annotations

import datetime
import io
import os
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.github import playwright_summary as ps

_TWO_SUITES_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="0" failures="0" skipped="0" time="0">
  <testsuite name="suite-a" tests="2" failures="1" skipped="0" time="3.5" timestamp="2026-05-17T12:00:00Z">
    <testcase name="passes" time="1.0"/>
    <testcase name="fails on assertion" time="2.5">
      <failure message="expected 1 got 0">stack-line-1\nstack-line-2</failure>
    </testcase>
  </testsuite>
  <testsuite name="suite-b" tests="2" failures="0" skipped="1" time="0.5" timestamp="2026-05-17T12:05:00Z">
    <testcase name="another pass" time="0.5"/>
    <testcase name="skipped one" time="0">
      <skipped message="persona blocked by env"/>
    </testcase>
  </testsuite>
</testsuites>"""

_ERROR_INSTEAD_OF_FAILURE_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="suite-c" time="1.0">
    <testcase name="crashes" time="1.0">
      <error message="ENOENT">no such file</error>
    </testcase>
  </testsuite>
</testsuites>"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestToIsoZ(unittest.TestCase):
    def test_utc_datetime_formats_with_z_suffix(self) -> None:
        self.assertEqual(
            ps._to_iso_z(
                datetime.datetime(2026, 5, 17, 12, 34, 56, tzinfo=datetime.UTC)
            ),
            "2026-05-17T12:34:56Z",
        )


class TestParseIsoTimestamp(unittest.TestCase):
    def test_empty_or_missing_returns_none(self) -> None:
        self.assertIsNone(ps._parse_iso_timestamp(""))
        self.assertIsNone(ps._parse_iso_timestamp(None))

    def test_unparseable_returns_none(self) -> None:
        self.assertIsNone(ps._parse_iso_timestamp("bogus"))

    def test_iso_with_z_suffix(self) -> None:
        result = ps._parse_iso_timestamp("2026-05-17T12:00:00Z")
        self.assertEqual(ps._to_iso_z(result), "2026-05-17T12:00:00Z")

    def test_naive_iso_treated_as_utc(self) -> None:
        result = ps._parse_iso_timestamp("2026-05-17T12:00:00")
        self.assertEqual(ps._to_iso_z(result), "2026-05-17T12:00:00Z")


class TestFormatDuration(unittest.TestCase):
    def test_sub_second_keeps_decimal(self) -> None:
        self.assertEqual(ps._format_duration(0.0), "0.0s")
        self.assertEqual(ps._format_duration(0.3), "0.3s")
        self.assertEqual(ps._format_duration(0.04), "0.0s")

    def test_sub_minute_keeps_decimal(self) -> None:
        self.assertEqual(ps._format_duration(12.5), "12.5s")
        self.assertEqual(ps._format_duration(59.9), "59.9s")

    def test_minute_boundary_rounds_seconds(self) -> None:
        self.assertEqual(ps._format_duration(60), "1m 0s")
        self.assertEqual(ps._format_duration(83.4), "1m 23s")
        self.assertEqual(ps._format_duration(3600), "60m 0s")


class TestFirstLine(unittest.TestCase):
    def test_none_returns_empty(self) -> None:
        self.assertEqual(ps._first_line(None), "")

    def test_whitespace_only_returns_empty(self) -> None:
        self.assertEqual(ps._first_line("   \n\t  "), "")

    def test_extracts_first_logical_line(self) -> None:
        self.assertEqual(
            ps._first_line("expected 1 got 0\nat /spec/foo.js:42"),
            "expected 1 got 0",
        )
        self.assertEqual(ps._first_line("  padded line  "), "padded line")


class TestMdEscapeCell(unittest.TestCase):
    def test_pipe_is_escaped(self) -> None:
        self.assertEqual(ps._md_escape_cell("a|b|c"), "a\\|b\\|c")

    def test_newlines_collapse_to_spaces(self) -> None:
        self.assertEqual(ps._md_escape_cell("line1\nline2"), "line1 line2")


class TestExtractRecords(unittest.TestCase):
    def test_mixed_pass_fail_skip(self) -> None:
        cases = list(
            ET.fromstring(_TWO_SUITES_FIXTURE).findall(".//testcase")  # noqa: S314 — fixture is hard-coded above
        )
        records = ps._extract_records(cases)
        self.assertEqual(
            records,
            [
                ("passes", "passed", "", 1.0),
                ("fails on assertion", "failed", "expected 1 got 0", 2.5),
                ("another pass", "passed", "", 0.5),
                ("skipped one", "skipped", "persona blocked by env", 0.0),
            ],
        )

    def test_error_child_counts_as_failed(self) -> None:
        cases = list(
            ET.fromstring(_ERROR_INSTEAD_OF_FAILURE_FIXTURE).findall(".//testcase")  # noqa: S314 — fixture is hard-coded above
        )
        records = ps._extract_records(cases)
        self.assertEqual(records, [("crashes", "failed", "ENOENT", 1.0)])

    def test_failure_with_only_text_uses_text(self) -> None:
        case = ET.fromstring(  # noqa: S314 — fixture literal, not user input
            '<testcase name="t"><failure>boom\nstack</failure></testcase>'
        )
        records = ps._extract_records([case])
        self.assertEqual(records, [("t", "failed", "boom", 0.0)])

    def test_skipped_without_message_yields_empty_string(self) -> None:
        case = ET.fromstring(  # noqa: S314 — fixture literal, not user input
            '<testcase name="anonymous-skip"><skipped/></testcase>'
        )
        records = ps._extract_records([case])
        self.assertEqual(records, [("anonymous-skip", "skipped", "", 0.0)])

    def test_malformed_time_falls_back_to_zero(self) -> None:
        case = ET.fromstring(  # noqa: S314 — fixture literal, not user input
            '<testcase name="bad-time" time="bogus"/>'
        )
        records = ps._extract_records([case])
        self.assertEqual(records, [("bad-time", "passed", "", 0.0)])


class TestPathInfo(unittest.TestCase):
    def test_full_variant_pass_layout(self) -> None:
        self.assertEqual(
            ps._path_info(
                Path("/tmp/root/web-app-foo/variant-3/async/playwright-junit.xml")
            ),
            ("web-app-foo", "3", "async"),
        )
        self.assertEqual(
            ps._path_info(
                Path("/tmp/root/web-app-foo/variant-0/sync/playwright-junit.xml")
            ),
            ("web-app-foo", "0", "sync"),
        )

    def test_variant_only_layout_leaves_pass_empty(self) -> None:
        self.assertEqual(
            ps._path_info(Path("/tmp/root/web-app-foo/variant-3/playwright-junit.xml")),
            ("web-app-foo", "3", ""),
        )

    def test_plain_layout_leaves_variant_and_pass_empty(self) -> None:
        self.assertEqual(
            ps._path_info(Path("/tmp/root/web-app-foo/playwright-junit.xml")),
            ("web-app-foo", "", ""),
        )

    def test_non_variant_subdir_falls_back_to_parent_only(self) -> None:
        # A directory whose name does not start with ``variant-`` is not
        # treated as a variant slot; the role uses that prefix as the
        # archive marker.
        self.assertEqual(
            ps._path_info(Path("/tmp/root/web-app-foo/leftover/playwright-junit.xml")),
            ("leftover", "", ""),
        )

    def test_pass_dir_without_variant_parent_is_not_recognized(self) -> None:
        # ``sync`` / ``async`` only count as pass markers when they sit
        # inside a ``variant-*`` directory; otherwise treat them as a
        # plain parent dir name.
        self.assertEqual(
            ps._path_info(Path("/tmp/root/web-app-foo/sync/playwright-junit.xml")),
            ("sync", "", ""),
        )


class TestSummarizeFile(unittest.TestCase):
    def test_plain_layout_fills_only_app(self) -> None:
        with TemporaryDirectory() as tmp:
            xml_path = _write(
                Path(tmp) / "web-app-foo" / "playwright-junit.xml", _TWO_SUITES_FIXTURE
            )
            summary = ps._summarize_file(xml_path)
        assert summary is not None
        self.assertEqual(summary["app"], "web-app-foo")
        self.assertEqual(summary["variant"], "")
        self.assertEqual(summary["pass"], "")
        self.assertEqual(len(summary["records"]), 4)
        # Per-case records are now 5-tuples (time, name, status, msg, duration).
        self.assertEqual(summary["records"][1][2], "failed")
        self.assertEqual(summary["records"][3][2], "skipped")
        self.assertAlmostEqual(summary["records"][0][4], 1.0)
        self.assertAlmostEqual(summary["records"][1][4], 2.5)

    def test_variant_and_pass_layout_populates_all_three_keys(self) -> None:
        with TemporaryDirectory() as tmp:
            xml_path = _write(
                Path(tmp)
                / "web-app-foo"
                / "variant-2"
                / "async"
                / "playwright-junit.xml",
                _TWO_SUITES_FIXTURE,
            )
            summary = ps._summarize_file(xml_path)
        assert summary is not None
        self.assertEqual(summary["app"], "web-app-foo")
        self.assertEqual(summary["variant"], "2")
        self.assertEqual(summary["pass"], "async")

    def test_per_case_timestamp_uses_suite_timestamp_plus_offset(self) -> None:
        with TemporaryDirectory() as tmp:
            xml_path = _write(
                Path(tmp) / "web-app-foo" / "playwright-junit.xml",
                _TWO_SUITES_FIXTURE,
            )
            summary = ps._summarize_file(xml_path)
        assert summary is not None
        records = summary["records"]
        # Suite-a starts at 12:00:00Z. First case starts there.
        self.assertEqual(records[0][0], "2026-05-17T12:00:00Z")
        # Second case starts after the first case's 1.0s duration.
        self.assertEqual(records[1][0], "2026-05-17T12:00:01Z")
        # Suite-b starts at 12:05:00Z — third case (first in suite-b).
        self.assertEqual(records[2][0], "2026-05-17T12:05:00Z")
        # Fourth case starts after the third's 0.5s duration.
        # Note: 12:05:00 + 0.5s → still 12:05:00 with second precision.
        self.assertEqual(records[3][0], "2026-05-17T12:05:00Z")

    def test_missing_timestamp_falls_back_to_file_mtime(self) -> None:
        no_timestamp_fixture = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<testsuites><testsuite name="t" time="1.0">'
            '<testcase name="ok" time="1.0"/>'
            "</testsuite></testsuites>"
        )
        with TemporaryDirectory() as tmp:
            xml_path = _write(
                Path(tmp) / "web-app-foo" / "playwright-junit.xml",
                no_timestamp_fixture,
            )
            # Force a known mtime so the fallback is deterministic.
            target = datetime.datetime(
                2025, 5, 17, 5, 34, 56, tzinfo=datetime.UTC
            ).timestamp()
            os.utime(xml_path, (target, target))
            summary = ps._summarize_file(xml_path)
        assert summary is not None
        self.assertEqual(summary["records"][0][0], "2025-05-17T05:34:56Z")

    def test_unparseable_returns_none(self) -> None:
        with TemporaryDirectory() as tmp:
            xml_path = _write(Path(tmp) / "x" / "playwright-junit.xml", "<broken")
            self.assertIsNone(ps._summarize_file(xml_path))

    def test_empty_testsuites_returns_none(self) -> None:
        with TemporaryDirectory() as tmp:
            xml_path = _write(
                Path(tmp) / "x" / "playwright-junit.xml",
                "<testsuites></testsuites>",
            )
            self.assertIsNone(ps._summarize_file(xml_path))


_T0 = "2026-05-17T12:00:00Z"


class TestRender(unittest.TestCase):
    def _summary(
        self,
        app: str,
        records: list[tuple[str, str, str, str, float]],
        *,
        variant: str = "",
        pass_: str = "",
    ) -> dict:
        return {"app": app, "variant": variant, "pass": pass_, "records": records}

    def test_emits_one_row_per_test_with_status_emoji(self) -> None:
        out = ps._render(
            [
                self._summary(
                    "web-app-foo",
                    [
                        (_T0, "test pass", "passed", "", 0.3),
                        (_T0, "test fail", "failed", "boom", 12.4),
                        (_T0, "test skip", "skipped", "blocked", 0.0),
                    ],
                    variant="variant-1",
                    pass_="sync",
                ),
            ],
            "web-app-foo",
        )
        self.assertIn("### 🎭 Playwright — web-app-foo", out)
        self.assertIn(
            "| Time | App | Variant | Pass | Test | Status | Duration | Message |",
            out,
        )
        self.assertIn(
            f"| `{_T0}` | `web-app-foo` | variant-1 | sync | test pass | 🟢 | 0.3s |  |",
            out,
        )
        self.assertIn(
            f"| `{_T0}` | `web-app-foo` | variant-1 | sync | test fail | 🔴 | 12.4s | boom |",
            out,
        )
        self.assertIn(
            f"| `{_T0}` | `web-app-foo` | variant-1 | sync | test skip | 🔵 | 0.0s | blocked |",
            out,
        )

    def test_status_legend_is_emitted(self) -> None:
        out = ps._render([self._summary("foo", [(_T0, "t", "passed", "", 1.0)])], "ctx")
        self.assertIn("🟢 passed", out)
        self.assertIn("🔴 failed", out)
        self.assertIn("🔵 skipped", out)

    def test_multiple_apps_grouped_in_single_table(self) -> None:
        out = ps._render(
            [
                self._summary(
                    "a",
                    [(_T0, "t1", "passed", "", 0.1)],
                    variant="variant-0",
                    pass_="sync",
                ),
                self._summary(
                    "b",
                    [(_T0, "t2", "failed", "x", 65.0)],
                    variant="variant-0",
                    pass_="async",
                ),
            ],
            "",
        )
        self.assertTrue(out.startswith("### 🎭 Playwright\n"))
        self.assertIn(f"| `{_T0}` | `a` | variant-0 | sync | t1 | 🟢 | 0.1s |  |", out)
        self.assertIn(
            f"| `{_T0}` | `b` | variant-0 | async | t2 | 🔴 | 1m 5s | x |", out
        )
        # Should have a single combined table, not two.
        self.assertEqual(
            out.count(
                "| Time | App | Variant | Pass | Test | Status | Duration | Message |"
            ),
            1,
        )

    def test_rows_are_sorted_ascending_by_time(self) -> None:
        out = ps._render(
            [
                self._summary(
                    "late",
                    [
                        ("2026-05-17T12:00:05Z", "late-1", "passed", "", 0.1),
                        ("2026-05-17T12:00:09Z", "late-2", "passed", "", 0.1),
                    ],
                ),
                self._summary(
                    "early",
                    [
                        ("2026-05-17T12:00:01Z", "early-1", "passed", "", 0.1),
                        ("2026-05-17T12:00:07Z", "early-2", "passed", "", 0.1),
                    ],
                ),
            ],
            "ctx",
        )
        body = out.split("|---|---|---|---|---|:---:|---:|---|\n", 1)[1]
        order = [line.split("|")[5].strip() for line in body.splitlines() if line]
        self.assertEqual(order, ["early-1", "late-1", "early-2", "late-2"])

    def test_plain_layout_leaves_variant_and_pass_cells_empty(self) -> None:
        out = ps._render(
            [self._summary("foo", [(_T0, "t1", "passed", "", 1.0)])],
            "ctx",
        )
        # Variant and Pass columns are present but empty for legacy/
        # single-run layouts.
        self.assertIn(f"| `{_T0}` | `foo` |  |  | t1 | 🟢 | 1.0s |  |", out)

    def test_message_is_truncated(self) -> None:
        long_msg = "x" * (ps._MAX_MSG_LEN + 50)
        out = ps._render(
            [self._summary("foo", [(_T0, "name", "failed", long_msg, 1.0)])],
            "ctx",
        )
        truncated = "x" * ps._MAX_MSG_LEN + "…"
        self.assertIn(truncated, out)

    def test_pipes_in_name_and_message_are_escaped(self) -> None:
        out = ps._render(
            [
                self._summary(
                    "foo",
                    [(_T0, 'up{job="x|y"} == 1', "failed", "got 0|1", 1.0)],
                )
            ],
            "ctx",
        )
        self.assertIn('up{job="x\\|y"} == 1', out)
        self.assertIn("got 0\\|1", out)


class TestMain(unittest.TestCase):
    def _run(self, *argv: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(ps, "sys") as fake_sys:
            fake_sys.argv = ["playwright_summary.py", *argv]
            fake_sys.stdout = stdout
            fake_sys.stderr = stderr
            rc = ps.main()
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_missing_argv_returns_two(self) -> None:
        rc, out, err = self._run()
        self.assertEqual(rc, 2)
        self.assertIn("Usage", err)
        self.assertEqual(out, "")

    def test_nonexistent_dir_emits_friendly_note(self) -> None:
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent"
            rc, out, _err = self._run(str(missing), "web-app-foo")
        self.assertEqual(rc, 0)
        self.assertIn("does not exist", out)
        self.assertIn("web-app-foo", out)

    def test_empty_dir_emits_no_junit_note(self) -> None:
        with TemporaryDirectory() as tmp:
            rc, out, _err = self._run(tmp, "web-app-foo")
        self.assertEqual(rc, 0)
        self.assertIn("No `playwright-junit.xml` found", out)

    def test_all_unparseable_emits_failure_note(self) -> None:
        with TemporaryDirectory() as tmp:
            _write(Path(tmp) / "x" / "playwright-junit.xml", "<broken")
            rc, out, _err = self._run(tmp, "web-app-foo")
        self.assertEqual(rc, 0)
        self.assertIn("failed to parse", out)

    def test_happy_path_renders_table(self) -> None:
        with TemporaryDirectory() as tmp:
            _write(
                Path(tmp)
                / "web-app-foo"
                / "variant-1"
                / "sync"
                / "playwright-junit.xml",
                _TWO_SUITES_FIXTURE,
            )
            rc, out, _err = self._run(tmp, "web-app-foo")
        self.assertEqual(rc, 0)
        self.assertIn("### 🎭 Playwright — web-app-foo", out)
        # Suite-a starts at 12:00:00Z; first case sits at that timestamp.
        self.assertIn(
            "| `2026-05-17T12:00:00Z` | `web-app-foo` | 1 | sync | passes | "
            "🟢 | 1.0s |  |",
            out,
        )
        self.assertIn(
            "| `2026-05-17T12:00:01Z` | `web-app-foo` | 1 | sync | "
            "fails on assertion | 🔴 | 2.5s | expected 1 got 0 |",
            out,
        )
        # Suite-b starts at 12:05:00Z; skipped case is its second testcase
        # (after a 0.5s pass that rounds to second-precision 0).
        self.assertIn(
            "| `2026-05-17T12:05:00Z` | `web-app-foo` | 1 | sync | "
            "skipped one | 🔵 | 0.0s | persona blocked by env |",
            out,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
