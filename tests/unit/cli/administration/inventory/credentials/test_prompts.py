"""Unit tests for ``cli.administration.inventory.credentials.prompts``."""

from __future__ import annotations

import unittest
import unittest.mock

from cli.administration.inventory.credentials.prompts import ask_for_confirmation


class TestAskForConfirmation(unittest.TestCase):
    def test_yes_returns_true(self):
        with unittest.mock.patch("builtins.input", return_value="y"):
            self.assertTrue(ask_for_confirmation("k"))

    def test_no_returns_false(self):
        with unittest.mock.patch("builtins.input", return_value="n"):
            self.assertFalse(ask_for_confirmation("k"))

    def test_arbitrary_response_returns_false(self):
        with unittest.mock.patch("builtins.input", return_value="maybe"):
            self.assertFalse(ask_for_confirmation("k"))

    def test_uppercase_y_is_normalised(self):
        with unittest.mock.patch("builtins.input", return_value="Y"):
            self.assertTrue(ask_for_confirmation("k"))

    def test_whitespace_is_stripped(self):
        with unittest.mock.patch("builtins.input", return_value="  y  "):
            self.assertTrue(ask_for_confirmation("k"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
