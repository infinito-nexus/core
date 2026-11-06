from __future__ import annotations

import contextlib
import io
import tarfile
import unittest
from pathlib import Path
from unittest import mock

from yaml.constructor import ConstructorError

from cli.administration.roles.paths import WORK_DIR
from cli.administration.roles.pull import command
from utils.cache import ROLES_DIR
from utils.roles.custom import CustomRoleError


class TestPullCommand(unittest.TestCase):
    @mock.patch.object(
        command, "pull", return_value=["web-app-cst-demo: repo path @ v1 (commit abc)"]
    )
    def test_pulls_the_inventory_into_the_core_roles(self, pull):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(0, command.main(["inv/devices.yml"]))
        pull.assert_called_once_with(Path("inv/devices.yml"), ROLES_DIR, WORK_DIR)
        self.assertIn("web-app-cst-demo: repo path @ v1 (commit abc)", out.getvalue())

    @mock.patch.object(command, "pull", return_value=[])
    def test_nothing_declared_or_placed_prints_nothing(self, _pull):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            command.main(["inv/devices.yml"])
        self.assertEqual("", out.getvalue())

    def test_unpacking_parsing_and_filesystem_errors_exit_1_naming_them(self):
        for error in (
            tarfile.AbsoluteLinkError(tarfile.TarInfo(".infinito-custom-role")),
            ConstructorError(None, None, "found an undefined tag in inv/hosts.yml"),
            PermissionError(13, "Permission denied", "roles/web-app-cst-demo"),
        ):
            with self.subTest(error=type(error).__name__):
                with (
                    mock.patch.object(command, "pull", side_effect=error),
                    contextlib.redirect_stderr(io.StringIO()) as err,
                    self.assertRaises(SystemExit) as exit_,
                ):
                    command.main(["inv/devices.yml"])
                self.assertEqual(1, exit_.exception.code)
                self.assertIn(str(error), err.getvalue())

    @mock.patch.object(
        command,
        "pull",
        side_effect=CustomRoleError(
            "web-app-cst-demo: git fetch of v1 failed: fatal: unable to access "
            "'https://deploy:s3cr3t@example.invalid/w.git/'"
        ),
    )
    def test_credentials_in_a_url_are_never_echoed(self, _pull):
        with (
            contextlib.redirect_stderr(io.StringIO()) as err,
            self.assertRaises(SystemExit),
        ):
            command.main(["inv/devices.yml"])
        self.assertNotIn("s3cr3t", err.getvalue())
        self.assertIn("web-app-cst-demo: git fetch of v1 failed", err.getvalue())

    @mock.patch.object(
        command, "pull", side_effect=CustomRoleError("web-app-cst-demo: refused")
    )
    def test_refused_pull_exits_1_with_the_reason(self, _pull):
        with (
            contextlib.redirect_stderr(io.StringIO()) as err,
            self.assertRaises(SystemExit) as exit_,
        ):
            command.main(["inv/devices.yml"])
        self.assertEqual(1, exit_.exception.code)
        self.assertIn("web-app-cst-demo: refused", err.getvalue())

    def test_inventory_argument_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            command.main([])


if __name__ == "__main__":
    unittest.main()
