from __future__ import annotations

import unittest

from utils.update.base import (
    is_semver,
    latest_semver,
    version_depth,
    version_flavor,
    version_key,
)


class TestUpdateBase(unittest.TestCase):
    def test_latest_semver_respects_depth(self) -> None:
        tags = ["4", "4.5", "4.6", "4.5.1", "5"]

        self.assertEqual(latest_semver(tags, 1), "5")
        self.assertEqual(latest_semver(tags, 2), "4.6")
        self.assertEqual(latest_semver(tags, 3), "4.5.1")

    def test_is_semver_accepts_flavored_tag(self) -> None:
        # Docker Official Image tags embed a runtime flavor after the
        # numeric semver, e.g. joomla:5.4.5-php8.3-apache.
        self.assertTrue(is_semver("5.4.5-php8.3-apache"))
        self.assertTrue(is_semver("v1.2.3-alpha"))
        # Non-numeric prefix (e.g. flowise's `main-v1.77.3.dynamic_rates`)
        # still MUST NOT be considered a semver tag.
        self.assertFalse(is_semver("main-v1.77.3.dynamic_rates"))
        self.assertFalse(is_semver("alpine"))

    def test_version_key_and_depth_ignore_flavor(self) -> None:
        self.assertEqual(version_key("5.4.5-php8.3-apache"), (5, 4, 5, 0))
        self.assertEqual(version_depth("5.4.5-php8.3-apache"), 3)
        self.assertEqual(version_flavor("5.4.5-php8.3-apache"), "-php8.3-apache")
        self.assertEqual(version_flavor("5.4.5"), "")

    def test_latest_semver_matches_flavor(self) -> None:
        tags = [
            "5.4.4-php8.3-apache",
            "5.4.5-php8.3-apache",
            "5.4.6-php8.3-apache",
            "5.4.6-php8.4-apache",
            "5.4.6-php8.3-fpm",
            "5.4.7",
            "alpine",
        ]

        self.assertEqual(
            latest_semver(tags, 3, "-php8.3-apache"),
            "5.4.6-php8.3-apache",
        )
        # Different flavor MUST NOT leak across as an upgrade candidate.
        self.assertEqual(
            latest_semver(tags, 3, "-php8.4-apache"),
            "5.4.6-php8.4-apache",
        )
        # Flavor-less current version MUST stay in the unflavored lane.
        self.assertEqual(latest_semver(tags, 3, ""), "5.4.7")


if __name__ == "__main__":
    unittest.main()
