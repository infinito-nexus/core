"""Unit tests for :mod:`utils.install.interpreters`."""

from __future__ import annotations

import unittest
import unittest.mock as mock

from utils.install import interpreters as interpreters_mod


class TestEnsureInterpretersPresent(unittest.TestCase):
    def test_installs_both_toolchains(self) -> None:
        with (
            mock.patch.object(interpreters_mod, "ensure_php_toolchain") as php,
            mock.patch.object(interpreters_mod, "ensure_ruby_present") as ruby,
        ):
            interpreters_mod.ensure_interpreters_present()
        php.assert_called_once_with()
        ruby.assert_called_once_with()

    def test_never_fetches_the_composer_vendor_tree(self) -> None:
        with (
            mock.patch.object(interpreters_mod, "ensure_php_toolchain"),
            mock.patch.object(interpreters_mod, "ensure_ruby_present"),
            mock.patch("utils.install.php.subprocess.run") as run,
        ):
            interpreters_mod.ensure_interpreters_present()
        run.assert_not_called()

    def test_propagates_the_hard_failure(self) -> None:
        with (
            mock.patch.object(
                interpreters_mod,
                "ensure_php_toolchain",
                side_effect=RuntimeError("boom"),
            ),
            mock.patch.object(interpreters_mod, "ensure_ruby_present") as ruby,
            self.assertRaises(RuntimeError),
        ):
            interpreters_mod.ensure_interpreters_present()
        ruby.assert_not_called()


if __name__ == "__main__":
    unittest.main()
