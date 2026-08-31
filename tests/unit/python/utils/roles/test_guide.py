import unittest
from typing import ClassVar
from unittest import mock

from utils.cache.applications import get_variants
from utils.roles.guide import guide_deployable, guide_variant, smallest_variant


def _variant(*enabled: str) -> dict:
    return {"services": {name: {"enabled": True} for name in enabled}}


class TestSmallestVariant(unittest.TestCase):
    def test_the_variant_with_the_fewest_enabled_services_wins(self) -> None:
        variants = [_variant("a", "b", "c"), _variant("a"), _variant("a", "b")]
        self.assertEqual(smallest_variant(variants), "1")

    def test_a_tie_goes_to_the_lower_index(self) -> None:
        self.assertEqual(smallest_variant([_variant("a"), _variant("b")]), "0")

    def test_a_disabled_service_does_not_count(self) -> None:
        variants = [
            {"services": {"a": {"enabled": True}, "b": {"enabled": False}}},
            _variant("a", "b"),
        ]
        self.assertEqual(smallest_variant(variants), "0")

    def test_a_variant_without_services_counts_as_empty(self) -> None:
        self.assertEqual(smallest_variant([_variant("a"), {}]), "1")

    def test_a_variant_the_sweep_cuts_hands_the_replay_on(self) -> None:
        """A row no sweep deploys would drop the role from the test entirely."""
        variants = [_variant("a"), _variant("a", "b"), _variant("a", "b", "c")]
        self.assertEqual(smallest_variant(variants, {"1", "2"}), "1")

    def test_a_role_with_no_deployed_variant_carries_nothing(self) -> None:
        self.assertEqual(smallest_variant([_variant("a")], set()), "")


class TestGuideVariant(unittest.TestCase):
    _VARIANTS: ClassVar[dict] = {"web-app-x": [_variant("a", "b"), _variant("a")]}
    _ALL: ClassVar[set] = {"0", "1"}

    def test_the_smallest_deployed_variant_carries_the_replay(self) -> None:
        with mock.patch("utils.roles.guide.guide_deployable", return_value="compose"):
            self.assertEqual(
                guide_variant("web-app-x", self._VARIANTS, self._ALL), ("1", "compose")
            )

    def test_a_role_the_guide_cannot_deploy_carries_nothing(self) -> None:
        with mock.patch("utils.roles.guide.guide_deployable", return_value=""):
            self.assertEqual(
                guide_variant("web-app-x", self._VARIANTS, self._ALL), ("", "")
            )

    def test_without_variant_data_no_row_is_the_smallest(self) -> None:
        self.assertEqual(guide_variant("web-app-x", None, self._ALL), ("", ""))
        self.assertEqual(guide_variant("web-app-x", {}, self._ALL), ("", ""))


class TestGuideDeployable(unittest.TestCase):
    """Against the real roles, which is what the marker is computed over."""

    def test_a_role_without_a_readme_production_block_is_excluded(self) -> None:
        self.assertEqual(guide_deployable("does-not-exist"), "")

    def test_the_mode_follows_whether_the_role_ships_a_stack(self) -> None:
        self.assertEqual(guide_deployable("web-app-nextcloud"), "compose")

    def test_the_replay_reaches_more_roles_than_the_single_random_pick(self) -> None:
        """The job it replaced tested exactly one role per run."""
        marked = [app for app in get_variants() if guide_deployable(app)]
        self.assertGreater(len(marked), 100)


if __name__ == "__main__":
    unittest.main()
