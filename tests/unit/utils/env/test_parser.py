"""Unit tests for :mod:`utils.env.parser`.

Covers ``parse_static_env`` and ``parse_static_env_with_comments``: line
shape, quote handling, inline-comment stripping, section-divider reset,
and the contiguous-comment-block extraction rule.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.env.parser import parse_static_env, parse_static_env_with_comments


def _write(td: str, body: str) -> Path:
    p = Path(td) / "default.env"
    p.write_text(body, encoding="utf-8")
    return p


class TestParseStaticEnvBasic(unittest.TestCase):
    def test_simple_key_value(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "K=v\n")
            self.assertEqual(parse_static_env(p), {"K": "v"})

    def test_multiple_entries(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "A=1\nB=two\nC=3\n")
            self.assertEqual(parse_static_env(p), {"A": "1", "B": "two", "C": "3"})

    def test_empty_value(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "K=\n")
            self.assertEqual(parse_static_env(p), {"K": ""})

    def test_blank_lines_ignored(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "\n\nA=1\n\nB=2\n\n")
            self.assertEqual(parse_static_env(p), {"A": "1", "B": "2"})


class TestParseStaticEnvQuoting(unittest.TestCase):
    def test_double_quoted_value(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, 'K="value with spaces"\n')
            self.assertEqual(parse_static_env(p), {"K": "value with spaces"})

    def test_single_quoted_value(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "K='single quoted'\n")
            self.assertEqual(parse_static_env(p), {"K": "single quoted"})

    def test_mismatched_quotes_not_stripped(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, 'K="open\n')
            # Mismatched quotes are kept; trailing "open" stays as-is.
            self.assertEqual(parse_static_env(p), {"K": '"open'})

    def test_inline_comment_stripped_unquoted(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "K=value # trailing\n")
            self.assertEqual(parse_static_env(p), {"K": "value"})

    def test_inline_hash_kept_in_quoted_value(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, 'K="a#b"\n')
            self.assertEqual(parse_static_env(p), {"K": "a#b"})


class TestParseStaticEnvComments(unittest.TestCase):
    def test_single_comment_above_key(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "# my doc\nK=v\n")
            _, comments = parse_static_env_with_comments(p)
            self.assertEqual(comments["K"], "my doc")

    def test_no_comment_means_no_entry(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "K=v\n")
            _, comments = parse_static_env_with_comments(p)
            self.assertNotIn("K", comments)

    def test_blank_line_breaks_comment_attachment(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "# orphan\n\nK=v\n")
            _, comments = parse_static_env_with_comments(p)
            self.assertNotIn("K", comments)

    def test_section_divider_does_not_attach(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "# --- Section A ---\nK=v\n")
            _, comments = parse_static_env_with_comments(p)
            self.assertNotIn("K", comments)

    def test_multi_line_comment_block_joined(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "# first line\n# second line\nK=v\n")
            _, comments = parse_static_env_with_comments(p)
            self.assertEqual(comments["K"], "first line second line")

    def test_only_immediate_block_attaches(self) -> None:
        with TemporaryDirectory() as td:
            body = "# earlier\n\n# closer\nK=v\n"
            p = _write(td, body)
            _, comments = parse_static_env_with_comments(p)
            self.assertEqual(comments["K"], "closer")

    def test_per_key_comments_independent(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "# doc-a\nA=1\n# doc-b\nB=2\n")
            _, comments = parse_static_env_with_comments(p)
            self.assertEqual(comments, {"A": "doc-a", "B": "doc-b"})


class TestParseStaticEnvErrors(unittest.TestCase):
    def test_unparseable_line_raises(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "not an assignment\n")
            with self.assertRaises(ValueError):
                parse_static_env(p)

    def test_error_message_includes_line_no(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "A=1\nbroken line\n")
            try:
                parse_static_env(p)
                self.fail("expected ValueError")
            except ValueError as exc:
                self.assertIn(":2:", str(exc))


class TestParseStaticEnvDelegates(unittest.TestCase):
    def test_parse_static_env_returns_only_values(self) -> None:
        with TemporaryDirectory() as td:
            p = _write(td, "# doc\nK=v\n")
            self.assertEqual(parse_static_env(p), {"K": "v"})


if __name__ == "__main__":
    unittest.main()
