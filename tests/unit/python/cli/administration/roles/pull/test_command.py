from __future__ import annotations

import contextlib
import io
import re
import tarfile
import unittest
import unittest.mock
from pathlib import Path

from yaml.constructor import ConstructorError

from cli.administration.roles.paths import WORK_DIR
from cli.administration.roles.pull import command
from utils.cache import PROJECT_ROOT, ROLES_DIR
from utils.cache.files import read_text
from utils.roles.custom import CustomRoleError


class TestPullCommand(unittest.TestCase):
    @unittest.mock.patch.object(
        command, "pull", return_value=["web-app-cst-demo: repo path @ v1 (commit abc)"]
    )
    def test_pulls_the_inventory_into_the_core_roles(self, pull):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(0, command.main(["inv/devices.yml"]))
        pull.assert_called_once_with(Path("inv/devices.yml"), ROLES_DIR, WORK_DIR)
        self.assertIn("web-app-cst-demo: repo path @ v1 (commit abc)", out.getvalue())

    @unittest.mock.patch.object(command, "pull", return_value=[])
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
                    unittest.mock.patch.object(command, "pull", side_effect=error),
                    contextlib.redirect_stderr(io.StringIO()) as err,
                    self.assertRaises(SystemExit) as exit_,
                ):
                    command.main(["inv/devices.yml"])
                self.assertEqual(1, exit_.exception.code)
                self.assertIn(str(error), err.getvalue())

    @unittest.mock.patch.object(
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

    @unittest.mock.patch.object(
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

    @unittest.mock.patch.object(command, "pull", return_value=[])
    def test_without_an_inventory_only_the_manifest_is_pulled(self, pull):
        self.assertEqual(0, command.main([]))
        pull.assert_called_once_with(None, ROLES_DIR, WORK_DIR)


class TestMakeTargetsPullFirst(unittest.TestCase):
    def test_test_and_lint_pull_the_pinned_roles_before_their_suites(self):
        makefile = read_text(str(PROJECT_ROOT / "Makefile"))
        for target in ("test", "lint"):
            with self.subTest(target=target):
                header = re.search(rf"(?m)^{target}:(.*)$", makefile)
                self.assertIsNotNone(header)
                self.assertIn("roles-pull", header[1].split())


if __name__ == "__main__":
    unittest.main()
