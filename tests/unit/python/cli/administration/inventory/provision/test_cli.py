from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.inventory.provision import cli as provision_cli

SECRET = "s3cret-become"


class VaultStepReachedError(Exception):
    pass


class UnreadableStdin(io.StringIO):
    def readline(self, *args, **kwargs):
        raise AssertionError("stdin was read without --become-password-stdin")


class TerminalStdin(UnreadableStdin):
    def isatty(self):
        return True


class TestReadBecomePassword(unittest.TestCase):
    def test_only_the_line_ending_is_stripped(self):
        for raw, expected in (
            (f"{SECRET}\n", SECRET),
            (f"{SECRET}\r\n", SECRET),
            (f"{SECRET} \n", f"{SECRET} "),
            (f"{SECRET} \r\n", f"{SECRET} "),
            (SECRET, SECRET),
            (f"{SECRET}\nsecond line\n", SECRET),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(
                    provision_cli._read_become_password(io.StringIO(raw)), expected
                )

    def test_an_empty_line_is_fatal(self):
        for raw in ("", "\n", "\r\n"):
            with self.subTest(raw=raw), self.assertRaises(SystemExit):
                provision_cli._read_become_password(io.StringIO(raw))

    def test_a_terminal_is_prompted_without_echo(self):
        with patch.object(
            provision_cli.getpass, "getpass", return_value=SECRET
        ) as prompt:
            self.assertEqual(
                provision_cli._read_become_password(TerminalStdin()), SECRET
            )
        prompt.assert_called_once()


class TestMainBecomePassword(unittest.TestCase):
    def _main(self, argv_tail: list[str], stdin: io.StringIO):
        with tempfile.TemporaryDirectory() as inventory_dir:
            argv = [str(Path(inventory_dir) / "inv"), *argv_tail]
            with (
                patch.object(
                    provision_cli,
                    "generate_dynamic_inventory",
                    return_value={"all": {"children": {}}},
                ),
                patch.object(provision_cli, "named_gateway_host", return_value=""),
                patch.object(provision_cli, "ensure_host_vars_file"),
                patch.object(provision_cli, "reconcile_services_disabled_from_env"),
                patch.object(
                    provision_cli,
                    "ensure_become_password",
                    side_effect=VaultStepReachedError,
                ) as vault,
                patch.object(provision_cli.sys, "stdin", stdin),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaises(VaultStepReachedError),
            ):
                provision_cli.main(argv)
        return argv, vault.call_args.kwargs

    def test_the_password_piped_on_stdin_is_vaulted(self):
        argv, kwargs = self._main(
            ["--become-password-stdin"], io.StringIO(f"{SECRET}\n")
        )
        self.assertEqual(kwargs["become_password"], SECRET)
        self.assertNotIn(SECRET, " ".join(argv))

    def test_without_the_flag_stdin_is_not_read(self):
        _argv, kwargs = self._main([], UnreadableStdin())
        self.assertIsNone(kwargs["become_password"])

    def test_a_password_on_argv_is_refused_without_being_printed(self):
        for argv in (
            ["inventories/x", "--become-password", SECRET],
            ["inventories/x", f"--become-password={SECRET}"],
            ["inventories/x", "--become-pass", SECRET],
            [f"--become={SECRET}", "inventories/x"],
            ["--become-pass", SECRET, "inventories/x"],
            ["--become-pass", SECRET],
            ["inventories/x", f"--become-password-stdin={SECRET}"],
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                self.subTest(argv=argv),
                patch.object(
                    provision_cli,
                    "detect_project_root",
                    side_effect=VaultStepReachedError,
                ),
                patch.object(provision_cli.sys, "stdin", UnreadableStdin()),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                provision_cli.main(argv)
            self.assertNotIn(SECRET, str(raised.exception.code))
            self.assertNotIn(SECRET, stdout.getvalue())
            self.assertNotIn(SECRET, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
