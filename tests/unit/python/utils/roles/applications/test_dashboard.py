"""Unit tests for ``utils/roles/applications/dashboard.py``."""

from __future__ import annotations

import unittest

from ansible.errors import AnsibleError

from utils.roles.applications.dashboard import card_target_key


class TestCardTargetKey(unittest.TestCase):
    def test_a_binding_without_the_key_targets_the_primary_domain(self):
        self.assertEqual(
            "", card_target_key("web-app-foo", {"enabled": True, "shared": True})
        )

    def test_a_missing_binding_targets_the_primary_domain(self):
        self.assertEqual("", card_target_key("web-app-foo", None))

    def test_the_named_key_is_returned(self):
        self.assertEqual(
            "element",
            card_target_key("web-app-matrix", {"card": "element"}),
        )

    def test_surrounding_whitespace_is_dropped(self):
        self.assertEqual(
            "webmail",
            card_target_key("web-app-stalwart", {"card": " webmail "}),
        )

    def test_an_alias_canonical_key_is_not_a_card_target(self):
        self.assertEqual("", card_target_key("web-svc-cdn", {"canonical": "cdn"}))

    def test_an_empty_key_fails_loudly(self):
        with self.assertRaisesRegex(AnsibleError, "web-app-foo"):
            card_target_key("web-app-foo", {"card": "  "})

    def test_a_non_string_key_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            card_target_key("web-app-foo", {"card": ["element"]})


if __name__ == "__main__":
    unittest.main()
