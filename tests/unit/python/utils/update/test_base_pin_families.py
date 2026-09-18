"""Immutable tags the updater could not order before.

Two shapes reach the repository that name a fixed release yet failed the semver
gate, so the bump job skipped them and nothing could tell whether a newer one
existed: a vendor patch counter such as ``2.4.0p32`` and a five-component
version such as ``26.04.2.1.1``.
"""

from __future__ import annotations

import unittest

from utils.update.base import (
    is_semver,
    latest_semver,
    version_depth,
    version_flavor,
    version_key,
)


def _latest(current: str, tags: list[str]) -> str | None:
    return latest_semver(tags, version_depth(current), version_flavor(current))


class TestPatchCounterTags(unittest.TestCase):
    def test_a_patch_counter_is_orderable(self):
        self.assertTrue(is_semver("2.4.0p32"))

    def test_it_bumps_within_its_own_counter(self):
        self.assertEqual(_latest("2.4.0p32", ["2.4.0p32", "2.4.0p33"]), "2.4.0p33")

    def test_the_counter_orders_numerically_not_lexically(self):
        self.assertEqual(_latest("2.4.0p9", ["2.4.0p9", "2.4.0p10"]), "2.4.0p10")

    def test_a_later_release_wins_over_a_later_counter(self):
        self.assertEqual(_latest("2.4.0p32", ["2.4.0p99", "2.4.1p1"]), "2.4.1p1")

    def test_it_never_crosses_into_a_four_component_version(self):
        self.assertEqual(
            _latest("2.4.0p32", ["2.4.0p32", "2.4.0.99"]),
            "2.4.0p32",
            "2.4.0.99 is a different tag family and bumping into it would "
            "silently change what the role deploys",
        )

    def test_the_counter_letter_keeps_families_apart(self):
        self.assertEqual(version_flavor("2.4.0p32"), "p")
        self.assertEqual(version_flavor("2.4.0.32"), "")
        self.assertNotEqual(version_depth("2.4.0p32"), version_depth("2.4.0.32"))

    def test_a_plain_release_does_not_bump_into_a_counter(self):
        self.assertEqual(_latest("2.4.0", ["2.4.0", "2.4.0p1"]), "2.4.0")


class TestFiveComponentTags(unittest.TestCase):
    def test_five_components_are_orderable(self):
        self.assertTrue(is_semver("26.04.2.1.1"))
        self.assertEqual(version_depth("26.04.2.1.1"), 5)

    def test_it_bumps_within_its_own_depth(self):
        self.assertEqual(
            _latest("26.04.2.1.1", ["26.04.2.1.1", "26.04.2.1.2"]), "26.04.2.1.2"
        )

    def test_it_never_crosses_into_a_shorter_version(self):
        self.assertEqual(
            _latest("26.04.2.1.1", ["26.04.2.1.1", "27.0.0.0"]), "26.04.2.1.1"
        )


class TestNothingElseChanged(unittest.TestCase):
    """The shapes the updater already handled must keep their family key."""

    def test_known_shapes_keep_their_classification(self):
        cases = {
            "1.2.3": (True, 3, "", (1, 2, 3, 0)),
            "v1.12.27": (True, 3, "", (1, 12, 27, 0)),
            "16": (True, 1, "", (16, 0, 0, 0)),
            "5.4.5-php8.3-apache": (True, 3, "-php8.3-apache", (5, 4, 5, 0)),
        }

        for tag, (semver, depth, flavor, key) in cases.items():
            self.assertEqual(is_semver(tag), semver, tag)
            self.assertEqual(version_depth(tag), depth, tag)
            self.assertEqual(version_flavor(tag), flavor, tag)
            self.assertEqual(version_key(tag), key, tag)

    def test_moving_names_are_still_refused(self):
        for tag in ("latest", "stable", "lts", "alpine", "main"):
            self.assertFalse(is_semver(tag), tag)

    def test_a_flavored_tag_still_refuses_a_different_runtime(self):
        self.assertEqual(
            _latest("5.4.5-php8.3-apache", ["5.4.6-php8.4-apache", "5.4.6"]),
            None,
        )


class TestChannelPrefixedTags(unittest.TestCase):
    """A release line written before the number is a family, not a version."""

    def test_a_channel_prefixed_tag_is_orderable(self):
        self.assertTrue(is_semver("main-v1.77.7-stable"))
        self.assertEqual(version_depth("main-v1.77.7-stable"), 3)
        self.assertEqual(version_key("main-v1.77.7-stable"), (1, 77, 7, 0))

    def test_it_bumps_inside_its_own_channel(self):
        tags = ["main-v1.77.7-stable", "main-v1.83.14-stable"]
        self.assertEqual(_latest("main-v1.77.7-stable", tags), "main-v1.83.14-stable")

    def test_it_never_crosses_into_a_sibling_channel(self):
        tags = ["main-v1.83.14-nightly", "main-v1.83.14-stable"]
        self.assertEqual(_latest("main-v1.77.7-stable", tags), "main-v1.83.14-stable")
        self.assertEqual(_latest("main-v1.77.7-nightly", tags), "main-v1.83.14-nightly")

    def test_a_bare_number_is_a_different_family_than_a_channelled_one(self):
        self.assertNotEqual(version_flavor("stable-9646"), version_flavor("9646"))
        self.assertEqual(
            _latest("stable-9646", ["stable-9646", "9999"]),
            "stable-9646",
            "a bare build number leaves the stable channel and would change "
            "what the role deploys",
        )

    def test_it_bumps_inside_the_stable_channel(self):
        self.assertEqual(
            _latest("stable-9646", ["stable-9646", "stable-9999"]), "stable-9999"
        )

    def test_a_channel_without_a_number_stays_refused(self):
        for tag in ("act-latest", "bookworm-slim", "main-latest", "buildx-stable-1"):
            self.assertFalse(is_semver(tag), tag)

    def test_a_date_stamped_tag_orders_as_one_number(self):
        self.assertEqual(version_depth("20260917"), 1)
        self.assertEqual(
            _latest("20260702", ["20260702", "20260706", "20260917"]), "20260917"
        )


if __name__ == "__main__":
    unittest.main()
