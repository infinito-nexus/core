"""Unit tests for :mod:`utils.install.lint.playwright`."""

from __future__ import annotations

import unittest
import unittest.mock as mock

from utils.install.lint import playwright as playwright_mod


class TestEnsure(unittest.TestCase):
    def test_a_stale_install_is_refreshed(self) -> None:
        with (
            mock.patch.object(
                playwright_mod,
                "npm_local_missing",
                side_effect=[["@axe-core/playwright"], []],
            ),
            mock.patch.object(playwright_mod, "npm_install_local_in_repo") as install,
        ):
            playwright_mod.ensure()
        install.assert_called_once()

    def test_a_complete_install_is_left_alone(self) -> None:
        with (
            mock.patch.object(playwright_mod, "npm_local_missing", return_value=[]),
            mock.patch.object(playwright_mod, "npm_install_local_in_repo") as install,
        ):
            playwright_mod.ensure()
        install.assert_not_called()

    def test_a_package_still_missing_after_the_install_fails_loud(self) -> None:
        with (
            mock.patch.object(
                playwright_mod,
                "npm_local_missing",
                return_value=["@axe-core/playwright"],
            ),
            mock.patch.object(playwright_mod, "npm_install_local_in_repo"),
            self.assertRaisesRegex(RuntimeError, "@axe-core/playwright"),
        ):
            playwright_mod.ensure()


if __name__ == "__main__":
    unittest.main()
