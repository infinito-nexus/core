"""The reduction from published platforms to where a role can be placed.

The intersection is the whole point: a role pins an application image beside
generic sidecars, and judging per image gets it wrong in both directions. It
would demand arm64 from an amd64-only role's nginx, and it would call a
narrowing stale because nginx publishes arm64 while the application does not.
"""

from __future__ import annotations

import unittest

from utils.docker.image.architectures import role_capability, runnable_architectures

BOTH = {"linux/amd64", "linux/arm64"}
AMD64 = {"linux/amd64"}
ARM64 = {"linux/arm64"}


class TestRunnableArchitectures(unittest.TestCase):
    def test_a_multi_platform_index_offers_both(self) -> None:
        self.assertEqual({"amd64", "arm64"}, runnable_architectures(BOTH))

    def test_a_foreign_os_carries_no_row(self) -> None:
        self.assertEqual(
            {"amd64"}, runnable_architectures({"linux/amd64", "windows/amd64"})
        )

    def test_an_unrotated_architecture_is_dropped(self) -> None:
        self.assertEqual(
            {"amd64"},
            runnable_architectures({"linux/amd64", "linux/ppc64le", "linux/s390x"}),
        )

    def test_an_empty_or_missing_set_offers_nothing(self) -> None:
        for platforms in (set(), None):
            with self.subTest(platforms=platforms):
                self.assertEqual(set(), runnable_architectures(platforms))


class TestRoleCapability(unittest.TestCase):
    def test_one_amd64_only_image_pins_the_whole_role(self) -> None:
        capability, blame, unread = role_capability({"app": AMD64, "nginx": BOTH})

        self.assertEqual({"amd64"}, capability)
        self.assertEqual({"arm64": ["app"]}, blame)
        self.assertEqual([], unread)

    def test_a_role_whose_images_all_publish_both_runs_on_both(self) -> None:
        capability, blame, _unread = role_capability({"app": BOTH, "nginx": BOTH})

        self.assertEqual({"amd64", "arm64"}, capability)
        self.assertEqual({}, blame)

    def test_images_pinned_to_opposite_architectures_run_nowhere(self) -> None:
        capability, blame, _unread = role_capability({"app": AMD64, "sidecar": ARM64})

        self.assertEqual(set(), capability)
        self.assertEqual({"amd64": ["sidecar"], "arm64": ["app"]}, blame)

    def test_blame_names_every_image_lacking_the_architecture(self) -> None:
        _capability, blame, _unread = role_capability(
            {"worker": AMD64, "app": AMD64, "nginx": BOTH}
        )

        self.assertEqual(["app", "worker"], blame["arm64"])

    def test_an_unreadable_image_is_reported_and_not_intersected(self) -> None:
        capability, blame, unread = role_capability({"app": BOTH, "unreadable": None})

        self.assertEqual(
            {"amd64", "arm64"},
            capability,
            "a throttled probe must understate, not narrow the role to nothing",
        )
        self.assertEqual({}, blame)
        self.assertEqual(
            ["unreadable"],
            unread,
            "without this the skipped image reads as one that runs everywhere, "
            "and a narrowing it alone justifies looks unnecessary",
        )

    def test_a_role_nobody_could_read_has_no_capability(self) -> None:
        capability, blame, unread = role_capability({"app": None, "nginx": None})

        self.assertIsNone(
            capability, "None is the skip signal, distinct from an empty set"
        )
        self.assertEqual({}, blame)
        self.assertEqual(["app", "nginx"], unread)

    def test_a_role_without_images_has_no_capability(self) -> None:
        self.assertEqual((None, {}, []), role_capability({}))


if __name__ == "__main__":
    unittest.main()
