"""Unit tests for ``utils/roles/applications/topics.py``.

The three override shapes have to stay distinguishable: ``null`` empties,
``{}`` is a no-op, and a mapping changes the keys it names and nothing else.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
    """The scan runs against a synthetic tree.

    No variant in ``roles/`` dictates a provider's config today, so scanning
    the real one would assert nothing and stay green however the function
    breaks.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.roles = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _role(self, name: str, services: str = "", variants: str = "") -> None:
        """Write the minimum a role needs to reach the service registry.

        Args:
            name: role directory name, also its ``application_id``.
            services: body of ``meta/services.yml``.
            variants: body of ``meta/variants.yml``, omitted when empty.
        """
        meta = self.roles / name / "meta"
        meta.mkdir(parents=True)
        variables = self.roles / name / "vars"
        variables.mkdir(parents=True)
        (variables / "main.yml").write_text(
            f"application_id: {name}\n", encoding="utf-8"
        )
        (meta / "services.yml").write_text(services or "{}\n", encoding="utf-8")
        if variants:
            (meta / "variants.yml").write_text(variants, encoding="utf-8")

    def test_it_records_the_provider_a_variant_dictates(self) -> None:
        self._role("svc-provider", "provider:\n  shared: true\n")
        self._role(
            "web-app-consumer",
            "provider:\n  enabled: true\n",
            "- services:\n    provider:\n      enabled: true\n      services: null\n",
        )
        self.assertEqual(
            {("web-app-consumer", 0): {"svc-provider"}},
            overridden_providers(self.roles),
        )

    def test_a_plain_flag_is_not_an_override(self) -> None:
        self._role("svc-provider", "provider:\n  shared: true\n")
        self._role(
            "web-app-consumer",
            "provider:\n  enabled: true\n",
            "- services:\n    provider:\n      enabled: true\n",
        )
        self.assertEqual({}, overridden_providers(self.roles))

    def test_a_role_never_records_itself(self) -> None:
        self._role(
            "svc-provider",
            "provider:\n  shared: true\n",
            "- services:\n    provider:\n      services: null\n",
        )
        self.assertEqual({}, overridden_providers(self.roles))


if __name__ == "__main__":
    unittest.main()
