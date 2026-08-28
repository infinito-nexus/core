"""Unit tests for :mod:`utils.install.php`."""

from __future__ import annotations

import subprocess
import unittest
import unittest.mock as mock

from utils.install import php as php_mod


class TestEnsurePhpToolchain(unittest.TestCase):
    def test_installs_the_binaries_and_the_phpunit_extensions(self) -> None:
        with (
            mock.patch.object(php_mod, "ensure_command_present") as ensure,
            mock.patch.object(php_mod, "ensure_php_extension_present") as extension,
            mock.patch.object(php_mod.subprocess, "run") as run,
        ):
            php_mod.ensure_php_toolchain()
        self.assertEqual(
            [c.args[0] for c in ensure.call_args_list],
            ["php", "composer", "unzip"],
        )
        self.assertEqual(
            [c.args[0] for c in extension.call_args_list],
            list(php_mod._PHPUNIT_EXTENSIONS),
        )
        run.assert_not_called()

    def test_covers_the_platform_requirements_composer_resolves(self) -> None:
        self.assertLessEqual(
            {"dom", "mbstring", "xmlwriter"}, set(php_mod._PHPUNIT_EXTENSIONS)
        )


class TestEnsurePhpPresent(unittest.TestCase):
    def test_vendor_tree_present_skips_composer(self) -> None:
        with (
            mock.patch.object(php_mod, "ensure_command_present") as ensure,
            mock.patch.object(php_mod, "ensure_php_extension_present"),
            mock.patch.object(php_mod, "_PHPUNIT") as phpunit,
            mock.patch.object(php_mod.subprocess, "run") as run,
        ):
            phpunit.is_file.return_value = True
            php_mod.ensure_php_present()
        self.assertEqual(
            [c.args[0] for c in ensure.call_args_list],
            ["php", "composer", "unzip"],
        )
        run.assert_not_called()

    def test_missing_vendor_tree_runs_composer_install(self) -> None:
        with (
            mock.patch.object(php_mod, "ensure_command_present"),
            mock.patch.object(php_mod, "ensure_php_extension_present"),
            mock.patch.object(php_mod, "_PHPUNIT") as phpunit,
            mock.patch.object(php_mod.subprocess, "run") as run,
        ):
            phpunit.is_file.side_effect = [False, True]
            php_mod.ensure_php_present()
        run.assert_called_once_with(
            ["composer", "install", "--no-interaction", "--no-progress"],
            cwd=php_mod.PROJECT_ROOT,
            check=True,
        )

    def test_raises_when_phpunit_still_missing(self) -> None:
        with (
            mock.patch.object(php_mod, "ensure_command_present"),
            mock.patch.object(php_mod, "ensure_php_extension_present"),
            mock.patch.object(php_mod, "_PHPUNIT") as phpunit,
            mock.patch.object(php_mod.subprocess, "run"),
            self.assertRaises(RuntimeError),
        ):
            phpunit.is_file.return_value = False
            php_mod.ensure_php_present()

    def test_propagates_a_failed_composer_install(self) -> None:
        with (
            mock.patch.object(php_mod, "ensure_command_present"),
            mock.patch.object(php_mod, "ensure_php_extension_present"),
            mock.patch.object(php_mod, "_PHPUNIT") as phpunit,
            mock.patch.object(
                php_mod.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "composer"),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            phpunit.is_file.return_value = False
            php_mod.ensure_php_present()

    def test_missing_interpreter_fails_before_composer(self) -> None:
        with (
            mock.patch.object(
                php_mod, "ensure_command_present", side_effect=RuntimeError("boom")
            ),
            mock.patch.object(php_mod, "ensure_php_extension_present"),
            mock.patch.object(php_mod.subprocess, "run") as run,
            self.assertRaises(RuntimeError),
        ):
            php_mod.ensure_php_present()
        run.assert_not_called()

    def test_missing_extension_fails_before_composer(self) -> None:
        with (
            mock.patch.object(php_mod, "ensure_command_present"),
            mock.patch.object(
                php_mod,
                "ensure_php_extension_present",
                side_effect=RuntimeError("ext-dom missing"),
            ),
            mock.patch.object(php_mod, "_PHPUNIT") as phpunit,
            mock.patch.object(php_mod.subprocess, "run") as run,
            self.assertRaises(RuntimeError),
        ):
            phpunit.is_file.return_value = False
            php_mod.ensure_php_present()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
