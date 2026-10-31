from __future__ import annotations

import unittest
from unittest.mock import patch

from cli.administration.inventory.provision import passwords


class TestPasswordMasking(unittest.TestCase):
    def test_a_user_password_is_registered_for_masking(self) -> None:
        with patch.object(passwords, "mask") as masked:
            password = passwords.generate_user_password()
        masked.assert_called_once_with(password)


if __name__ == "__main__":
    unittest.main()
