"""Unit tests for ``utils/roles/applications/topics.py``.

The three override shapes have to stay distinguishable: ``null`` empties,
``{}`` is a no-op, and a mapping changes the keys it names and nothing else.
"""

from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.roles.applications.topics import (
    CONFIG_TOPICS,
    apply_topic,
    overridden_providers,
)


class TestApplyTopic(unittest.TestCase):
    def test_null_empties_the_topic(self):
        self.assertEqual({}, apply_topic({"a": {"enabled": True}}, None))

    def test_an_empty_mapping_changes_nothing(self):
        base = {"a": {"enabled": True}}
        self.assertEqual(base, apply_topic(base, {}))

    def test_a_mapping_merges_the_named_keys_only(self):
        base = {"a": {"enabled": True}, "b": {"enabled": True}}
        self.assertEqual(
            {"a": {"enabled": False}, "b": {"enabled": True}},
            apply_topic(base, {"a": {"enabled": False}}),
        )

    def test_a_missing_base_still_takes_the_override(self):
        self.assertEqual({"a": 1}, apply_topic(None, {"a": 1}))

    def test_the_vocabulary_covers_the_topics_a_variant_can_name(self):
        self.assertIn("services", CONFIG_TOPICS)
        self.assertIn("addons", CONFIG_TOPICS)
        self.assertNotIn("enabled", CONFIG_TOPICS)


class TestOverriddenProviders(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.found = overridden_providers(PROJECT_ROOT / "roles")

    def test_the_scan_finds_the_declared_overrides(self) -> None:
        self.assertTrue(self.found)

    def test_a_role_never_records_itself(self) -> None:
        self.assertEqual(
            [],
            [(role, i) for (role, i), targets in self.found.items() if role in targets],
        )

    def test_every_target_is_a_role_that_exists(self) -> None:
        roles = {p.name for p in (PROJECT_ROOT / "roles").iterdir() if p.is_dir()}
        missing = sorted(
            {target for targets in self.found.values() for target in targets} - roles
        )
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
