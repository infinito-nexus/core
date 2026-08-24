import unittest
from unittest.mock import patch

import cli.__main__ as entrypoint


class TestCliEntrypoint(unittest.TestCase):
    def test_entrypoint_calls_core_main(self):
        with patch("cli.__main__.main") as mock_main:
            entrypoint.main()
            mock_main.assert_called_once()


if __name__ == "__main__":
    unittest.main()
