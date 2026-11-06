from __future__ import annotations

import os
import unittest
from io import StringIO
from unittest.mock import patch

from utils.annotations.message import (
    error,
    error_each,
    mask,
    notice,
    warning,
    warning_each,
)

GHA_ENV = {"GITHUB_ACTIONS": "true"}
NO_GHA_ENV = {"GITHUB_ACTIONS": ""}


class TestAnnotationsInGHA(unittest.TestCase):
    """Tests for GHA annotation format (GITHUB_ACTIONS=true)."""

    def _capture(self, fn, *args, **kwargs) -> str:
        with (
            patch.dict(os.environ, GHA_ENV),
            patch("sys.stdout", new_callable=StringIO) as mock_out,
        ):
            fn(*args, **kwargs)
            return mock_out.getvalue().strip()

    def test_warning_no_props(self) -> None:
        out = self._capture(warning, "something went wrong")
        self.assertEqual(out, "::warning::something went wrong")

    def test_warning_with_title(self) -> None:
        out = self._capture(warning, "msg", title="My Title")
        self.assertEqual(out, "::warning title=My Title::msg")

    def test_warning_with_file_and_line(self) -> None:
        out = self._capture(warning, "msg", file="foo.py", line=42)
        self.assertEqual(out, "::warning file=foo.py,line=42::msg")

    def test_error_with_title(self) -> None:
        out = self._capture(error, "bad", title="Oops")
        self.assertEqual(out, "::error title=Oops::bad")

    def test_notice_no_props(self) -> None:
        out = self._capture(notice, "info")
        self.assertEqual(out, "::notice::info")

    def test_warning_each_emits_one_per_item(self) -> None:
        with (
            patch.dict(os.environ, GHA_ENV),
            patch("sys.stdout", new_callable=StringIO) as mock_out,
        ):
            warning_each(["alpha", "beta", "gamma"], title="T")
            lines = mock_out.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("alpha", lines[0])
        self.assertIn("beta", lines[1])
        self.assertIn("gamma", lines[2])

    def test_error_each_emits_one_per_item(self) -> None:
        with (
            patch.dict(os.environ, GHA_ENV),
            patch("sys.stdout", new_callable=StringIO) as mock_out,
        ):
            error_each(["x", "y"], title="E")
            lines = mock_out.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("::error" in line for line in lines))

    def test_warning_each_empty(self) -> None:
        with (
            patch.dict(os.environ, GHA_ENV),
            patch("sys.stdout", new_callable=StringIO) as mock_out,
        ):
            warning_each([])
            self.assertEqual(mock_out.getvalue(), "")


class TestAnnotationsPlainText(unittest.TestCase):
    """Tests for plain text format (no GITHUB_ACTIONS)."""

    def _capture(self, fn, *args, **kwargs) -> str:
        with (
            patch.dict(os.environ, NO_GHA_ENV),
            patch("sys.stdout", new_callable=StringIO) as mock_out,
        ):
            fn(*args, **kwargs)
            return mock_out.getvalue().strip()

    def test_warning_no_props(self) -> None:
        out = self._capture(warning, "something went wrong")
        self.assertEqual(out, "[WARNING]: something went wrong")

    def test_warning_with_title(self) -> None:
        out = self._capture(warning, "msg", title="My Title")
        self.assertEqual(out, "[WARNING] My Title: msg")

    def test_error_with_title(self) -> None:
        out = self._capture(error, "bad", title="Oops")
        self.assertEqual(out, "[ERROR] Oops: bad")

    def test_notice_no_props(self) -> None:
        out = self._capture(notice, "info")
        self.assertEqual(out, "[NOTICE]: info")

    def test_warning_each_emits_one_per_item(self) -> None:
        with (
            patch.dict(os.environ, NO_GHA_ENV),
            patch("sys.stdout", new_callable=StringIO) as mock_out,
        ):
            warning_each(["alpha", "beta"], title="T")
            lines = mock_out.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("alpha", lines[0])
        self.assertIn("beta", lines[1])


class TestMask(unittest.TestCase):
    def _capture(self, env: dict[str, str], value: str) -> tuple[str, str]:
        with (
            patch.dict(os.environ, env),
            patch("sys.stdout", new_callable=StringIO) as out,
            patch("sys.stderr", new_callable=StringIO) as err,
        ):
            mask(value)
            return out.getvalue(), err.getvalue()

    def test_a_secret_is_registered_on_stderr_only(self) -> None:
        out, err = self._capture(GHA_ENV, "s3cr€t")
        self.assertEqual(out, "")
        self.assertEqual(err, "::add-mask::s3cr€t\n")

    def test_each_line_of_a_multiline_secret_is_registered(self) -> None:
        _, err = self._capture(GHA_ENV, "-----BEGIN-----\nabc\n\n-----END-----\n")
        self.assertEqual(
            err.splitlines(),
            [
                "::add-mask::-----BEGIN-----",
                "::add-mask::abc",
                "::add-mask::-----END-----",
            ],
        )

    def test_nothing_is_printed_outside_github_actions(self) -> None:
        self.assertEqual(self._capture(NO_GHA_ENV, "s3cret"), ("", ""))


if __name__ == "__main__":
    unittest.main()
