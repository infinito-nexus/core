import unittest
from unittest.mock import patch

from cli.core import colors


class TestColors(unittest.TestCase):
    @patch("cli.core.colors.Style")
    def test_color_text_wraps_text_with_color_and_reset(self, mock_style):
        mock_style.RESET_ALL = "<RESET>"
        result = colors.color_text("Hello", "<C>")
        self.assertEqual(result, "<C>Hello<RESET>")


if __name__ == "__main__":
    unittest.main()
