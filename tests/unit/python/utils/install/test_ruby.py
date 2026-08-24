"""Unit tests for :mod:`utils.install.ruby`."""

from __future__ import annotations

import unittest
import unittest.mock as mock

from utils.install import ruby as ruby_mod


class TestEnsureRubyPresent(unittest.TestCase):
    def test_delegates_to_the_shared_provisioner(self) -> None:
        with mock.patch.object(ruby_mod, "ensure_command_present") as ensure:
            ruby_mod.ensure_ruby_present()
        ensure.assert_called_once_with("ruby")

    def test_propagates_the_hard_failure(self) -> None:
        with (
            mock.patch.object(
                ruby_mod, "ensure_command_present", side_effect=RuntimeError("boom")
            ),
            self.assertRaises(RuntimeError),
        ):
            ruby_mod.ensure_ruby_present()


if __name__ == "__main__":
    unittest.main()
