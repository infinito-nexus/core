from __future__ import annotations

import unittest

from utils.roles.custom import is_custom, is_custom_path
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN


class TestIsCustom(unittest.TestCase):
    def test_reserved_prefix_is_custom(self):
        self.assertTrue(is_custom("web-app-cst-security-check"))

    def test_in_tree_application_is_not_custom(self):
        self.assertFalse(is_custom("web-app-nextcloud"))

    def test_category_name_alone_is_not_custom(self):
        self.assertFalse(is_custom("web-app-cst"))


class TestIsCustomPath(unittest.TestCase):
    def test_file_in_a_placed_custom_role(self):
        self.assertTrue(
            is_custom_path(f"roles/web-app-cst-store/{ROLE_FILE_TASKS_MAIN}")
        )

    def test_file_in_an_in_tree_role(self):
        self.assertFalse(
            is_custom_path(f"roles/web-app-nextcloud/{ROLE_FILE_TASKS_MAIN}")
        )

    def test_custom_prefix_outside_roles(self):
        self.assertFalse(is_custom_path("docs/web-app-cst-store/README.md"))

    def test_roles_directory_itself(self):
        self.assertFalse(is_custom_path("roles"))


if __name__ == "__main__":
    unittest.main()
