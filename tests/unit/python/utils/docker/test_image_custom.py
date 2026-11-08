from __future__ import annotations

import unittest
from unittest.mock import Mock

from utils.docker.image.custom import custom_image_name


class TestCustomImageName(unittest.TestCase):
    def test_true_names_the_image_after_the_entity(self):
        self.assertEqual(
            custom_image_name(True, lambda: "mattermost"), "mattermost_custom"
        )

    def test_a_string_names_the_image_itself(self):
        self.assertEqual(
            custom_image_name("nextcloud-whiteboard", lambda: "nextcloud"),
            "nextcloud-whiteboard_custom",
        )

    def test_a_string_never_asks_for_the_entity(self):
        entity_name = Mock(return_value="nextcloud")
        custom_image_name("side", entity_name)
        entity_name.assert_not_called()

    def test_surrounding_whitespace_is_dropped(self):
        self.assertEqual(custom_image_name("  side  ", lambda: "x"), "side_custom")
        self.assertEqual(
            custom_image_name(True, lambda: " mattermost "), "mattermost_custom"
        )

    def test_a_blank_string_names_the_image_after_the_entity(self):
        self.assertEqual(
            custom_image_name("   ", lambda: "mattermost"), "mattermost_custom"
        )

    def test_no_base_names_no_image(self):
        self.assertEqual(custom_image_name(True, lambda: ""), "")


if __name__ == "__main__":
    unittest.main()
