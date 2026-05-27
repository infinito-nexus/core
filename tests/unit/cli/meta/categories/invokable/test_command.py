from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import yaml

from cli.meta.categories.invokable import command


class TestInvokableCategoriesCommand(unittest.TestCase):
    def _run_main(self, argv: list[str]) -> tuple[int, str, str]:
        """
        Run command.main() with patched sys.argv and capture stdout/stderr.

        Returns: (exit_code, stdout, stderr)
        """
        out = io.StringIO()
        err = io.StringIO()

        with (
            patch("sys.argv", ["prog", *argv]),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            try:
                command.main()
            except SystemExit as exc:
                code = exc.code if exc.code is not None else 0
                return int(code), out.getvalue(), err.getvalue()

        # If no SystemExit was raised, it succeeded
        return 0, out.getvalue(), err.getvalue()

    @patch("cli.meta.categories.invokable.command.get_invokable_paths")
    @patch("cli.meta.categories.invokable.command.get_non_invokable_paths")
    def test_default_lists_invokable(self, mock_non_invokable, mock_invokable) -> None:
        mock_invokable.return_value = ["a/b", "c/d"]
        mock_non_invokable.return_value = ["x/y"]

        code, stdout, stderr = self._run_main([])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.splitlines(), ["a/b", "c/d"])

        mock_invokable.assert_called_once_with(None, None)
        mock_non_invokable.assert_not_called()

    @patch("cli.meta.categories.invokable.command.get_invokable_paths")
    @patch("cli.meta.categories.invokable.command.get_non_invokable_paths")
    def test_non_invokable_flag_lists_non_invokable(
        self, mock_non_invokable, mock_invokable
    ) -> None:
        mock_non_invokable.return_value = ["n1", "n2"]

        code, stdout, stderr = self._run_main(["--non-invokable"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.splitlines(), ["n1", "n2"])

        mock_non_invokable.assert_called_once_with(None, None)
        mock_invokable.assert_not_called()

    @patch("cli.meta.categories.invokable.command.get_invokable_paths")
    def test_roles_file_and_suffix_are_forwarded(self, mock_invokable) -> None:
        mock_invokable.return_value = ["p1"]

        code, stdout, stderr = self._run_main(["roles/categories.yml", "--suffix", "-"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.splitlines(), ["p1"])

        mock_invokable.assert_called_once_with("roles/categories.yml", "-")

    @patch("cli.meta.categories.invokable.command.get_invokable_paths")
    def test_short_suffix_flag(self, mock_invokable) -> None:
        mock_invokable.return_value = ["p1"]

        code, stdout, stderr = self._run_main(["-s", "::"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.splitlines(), ["p1"])

        mock_invokable.assert_called_once_with(None, "::")

    @patch("cli.meta.categories.invokable.command.get_invokable_paths")
    def test_file_not_found_exits_1_and_prints_error(self, mock_invokable) -> None:
        mock_invokable.side_effect = FileNotFoundError("missing file")

        code, stdout, stderr = self._run_main([])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Error: missing file", stderr)

    @patch("cli.meta.categories.invokable.command.get_invokable_paths")
    def test_yaml_error_exits_1(self, mock_invokable) -> None:
        mock_invokable.side_effect = yaml.YAMLError("bad yaml")

        code, stdout, stderr = self._run_main([])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Error parsing YAML:", stderr)

    @patch("cli.meta.categories.invokable.command.get_invokable_paths")
    def test_value_error_exits_1(self, mock_invokable) -> None:
        mock_invokable.side_effect = ValueError("bad value")

        code, stdout, stderr = self._run_main([])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Error: bad value", stderr)


if __name__ == "__main__":
    unittest.main()
