"""Unit tests for :mod:`utils.install.ruby`."""

from __future__ import annotations

import unittest
import unittest.mock as mock

from utils.install import ruby as ruby_mod


class TestEnsureRubyPresent(unittest.TestCase):
    def test_provisions_ruby_then_minitest(self) -> None:
        calls = mock.Mock()
        with (
            mock.patch.object(ruby_mod, "ensure_command_present", calls.ruby),
            mock.patch.object(ruby_mod, "ensure_minitest_present", calls.minitest),
        ):
            ruby_mod.ensure_ruby_present()
        self.assertEqual(
            calls.mock_calls, [mock.call.ruby("ruby"), mock.call.minitest()]
        )

    def test_propagates_the_hard_failure(self) -> None:
        with (
            mock.patch.object(
                ruby_mod, "ensure_command_present", side_effect=RuntimeError("boom")
            ),
            mock.patch.object(ruby_mod, "ensure_minitest_present") as minitest,
            self.assertRaises(RuntimeError),
        ):
            ruby_mod.ensure_ruby_present()
        minitest.assert_not_called()


class TestEnsureMinitestPresent(unittest.TestCase):
    def run_with(self, *, loadable: list[bool], manager: str) -> mock.Mock:
        """Run ``ensure_minitest_present`` with stubbed probe and installer.

        Args:
            loadable: successive results of the minitest probe.
            manager: package manager the host reports.

        Returns:
            The stubbed ``install_package_candidates``.
        """
        with (
            mock.patch.object(ruby_mod, "minitest_loadable", side_effect=loadable),
            mock.patch.object(ruby_mod, "detect_package_manager", return_value=manager),
            mock.patch.object(ruby_mod, "install_package_candidates") as install,
            mock.patch.object(ruby_mod, "log"),
        ):
            ruby_mod.ensure_minitest_present()
        return install

    def test_a_loadable_minitest_installs_nothing(self) -> None:
        install = self.run_with(loadable=[True], manager="pacman")
        install.assert_not_called()

    def test_arch_installs_ruby_minitest(self) -> None:
        install = self.run_with(loadable=[False, True], manager="pacman")
        install.assert_called_once_with("pacman", ["ruby-minitest"])

    def test_the_redhat_family_installs_rubygem_minitest(self) -> None:
        install = self.run_with(loadable=[False, True], manager="dnf")
        install.assert_called_once_with("dnf", ["rubygem-minitest"])

    def test_still_missing_after_the_install_fails_loudly(self) -> None:
        with self.assertRaises(RuntimeError):
            self.run_with(loadable=[False, False], manager="pacman")

    def test_an_unmapped_manager_fails_without_installing(self) -> None:
        with (
            mock.patch.object(ruby_mod, "minitest_loadable", return_value=False),
            mock.patch.object(ruby_mod, "detect_package_manager", return_value="brew"),
            mock.patch.object(ruby_mod, "install_package_candidates") as install,
            mock.patch.object(ruby_mod, "log"),
            self.assertRaises(RuntimeError),
        ):
            ruby_mod.ensure_minitest_present()
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
