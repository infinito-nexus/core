from __future__ import annotations

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from utils.annotations.summarize import (
    Annotation,
    main,
    parse_log,
    parse_props,
    render_markdown,
)
from utils.cache.files import read_text


class TestParseProps(unittest.TestCase):
    def test_single_prop(self) -> None:
        self.assertEqual(parse_props("title=Foo"), {"title": "Foo"})

    def test_multiple_props(self) -> None:
        result = parse_props("title=My Title,file=foo.py,line=42")
        self.assertEqual(result, {"title": "My Title", "file": "foo.py", "line": "42"})

    def test_empty_string(self) -> None:
        self.assertEqual(parse_props(""), {})

    def test_none_like_empty(self) -> None:
        self.assertEqual(parse_props(""), {})


class TestParseLog(unittest.TestCase):
    def _write_log(self, content: str) -> Path:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
        return Path(f.name)

    def test_parses_warning(self) -> None:
        p = self._write_log("::warning title=T,file=f.py,line=3::bad thing\n")
        result = parse_log(p)
        self.assertEqual(len(result), 1)
        a = result[0]
        self.assertEqual(a.level, "warning")
        self.assertEqual(a.title, "T")
        self.assertEqual(a.file, "f.py")
        self.assertEqual(a.line, 3)
        self.assertEqual(a.message, "bad thing")

    def test_parses_error(self) -> None:
        p = self._write_log("::error title=Oops::something broke\n")
        result = parse_log(p)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].level, "error")
        self.assertEqual(result[0].title, "Oops")

    def test_parses_notice(self) -> None:
        p = self._write_log("::notice::just info\n")
        result = parse_log(p)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].level, "notice")
        self.assertIsNone(result[0].title)

    def test_ignores_non_annotation_lines(self) -> None:
        p = self._write_log("regular output\nsome other line\n")
        self.assertEqual(parse_log(p), [])

    def test_mixed_log(self) -> None:
        content = (
            "build started\n"
            "::warning title=W::warn msg\n"
            "some output\n"
            "::error::err msg\n"
        )
        p = self._write_log(content)
        result = parse_log(p)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].level, "warning")
        self.assertEqual(result[1].level, "error")

    def test_multiple_annotations(self) -> None:
        lines = "\n".join(f"::warning::msg {i}" for i in range(15))
        p = self._write_log(lines)
        self.assertEqual(len(parse_log(p)), 15)


class TestRenderMarkdown(unittest.TestCase):
    def test_empty_returns_no_annotations_message(self) -> None:
        md = render_markdown([], "My Title")
        self.assertIn("My Title", md)
        self.assertIn("No annotations found", md)

    def test_warning_section_present(self) -> None:
        annotations = [Annotation(level="warning", message="watch out", title="T")]
        md = render_markdown(annotations, "Summary")
        self.assertIn("Warnings", md)
        self.assertIn("watch out", md)
        self.assertIn("🟡", md)

    def test_error_section_present(self) -> None:
        annotations = [Annotation(level="error", message="broken")]
        md = render_markdown(annotations, "Summary")
        self.assertIn("Errors", md)
        self.assertIn("🔴", md)

    def test_notice_section_present(self) -> None:
        annotations = [Annotation(level="notice", message="fyi")]
        md = render_markdown(annotations, "Summary")
        self.assertIn("Notices", md)
        self.assertIn("🔵", md)

    def test_file_with_line_shown_as_colon_path(self) -> None:
        annotations = [Annotation(level="warning", message="x", file="a.py", line=7)]
        md = render_markdown(annotations, "S")
        self.assertIn("a.py:7", md)

    def test_pipe_in_message_escaped(self) -> None:
        annotations = [Annotation(level="warning", message="a|b")]
        md = render_markdown(annotations, "S")
        self.assertIn("a\\|b", md)

    def test_count_in_heading(self) -> None:
        annotations = [
            Annotation(level="warning", message="w1"),
            Annotation(level="warning", message="w2"),
        ]
        md = render_markdown(annotations, "S")
        self.assertIn("Warnings (2)", md)

    def test_order_error_warning_notice(self) -> None:
        annotations = [
            Annotation(level="notice", message="n"),
            Annotation(level="warning", message="w"),
            Annotation(level="error", message="e"),
        ]
        md = render_markdown(annotations, "S")
        error_pos = md.index("Errors")
        warning_pos = md.index("Warnings")
        notice_pos = md.index("Notices")
        self.assertLess(error_pos, warning_pos)
        self.assertLess(warning_pos, notice_pos)


class TestMain(unittest.TestCase):
    def test_writes_to_github_step_summary(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as log:
            log.write("::warning title=T::msg\n")
            log_path = log.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as summary:
            summary_path = summary.name

        old_argv = sys.argv
        try:
            sys.argv = ["summarize", log_path, "Test Title"]
            with unittest.mock.patch.dict(
                os.environ, {"GITHUB_STEP_SUMMARY": summary_path}
            ):
                main()
        finally:
            sys.argv = old_argv

        content = read_text(summary_path)
        self.assertIn("Test Title", content)
        self.assertIn("msg", content)

    def test_exits_without_args(self) -> None:
        old_argv = sys.argv
        sys.argv = ["summarize"]
        try:
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
