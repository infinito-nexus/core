"""Unit tests for :mod:`utils.i18n.names` and the span merge that consumes it.

The cases use names the repository really ships, so a renamed role shows up here
rather than in a silently weakened protection.
"""

from __future__ import annotations

import unittest
from itertools import pairwise

from utils.i18n.names import spans
from utils.i18n.placeholders import (
    has_words,
    matches,
    missing_names,
    protected_spans,
)


def _protected(text: str) -> set[str]:
    return {text[start:end] for start, end in matches(text)}


class TestRoleNames(unittest.TestCase):
    def test_a_role_name_is_protected_mid_sentence(self) -> None:
        self.assertIn("web-app-keycloak", _protected("Deploy web-app-keycloak first"))

    def test_a_role_name_is_protected_at_the_start(self) -> None:
        self.assertIn("web-app-keycloak", _protected("web-app-keycloak issues tokens"))

    def test_a_longer_identifier_is_not_cut_short(self) -> None:
        self.assertNotIn("web-app", _protected("Deploy web-app-keycloak first"))

    def test_ordinary_hyphenated_english_stays_translatable(self) -> None:
        self.assertNotIn("self-hosted", _protected("A self-hosted open-source service"))


class TestTitles(unittest.TestCase):
    def test_a_title_inside_a_sentence_is_protected(self) -> None:
        self.assertIn("Keycloak", _protected("The realm Keycloak issues tokens for"))

    def test_a_title_that_is_also_an_adjective_is_protected_inside_a_sentence(
        self,
    ) -> None:
        self.assertIn("Unbound", _protected("DNS resolver engines (Unbound, etc.)"))

    def test_a_heading_stays_translatable(self) -> None:
        self.assertNotIn("Documentation", _protected("Documentation and Wiki Apps"))

    def test_a_title_opening_a_sentence_stays_translatable(self) -> None:
        self.assertNotIn("Keycloak", _protected("Keycloak issues the token"))

    def test_a_lowercase_reading_stays_translatable(self) -> None:
        self.assertNotIn("shell", _protected("bundling caffeine, shell extensions"))

    def test_a_lowercase_common_noun_stays_translatable(self) -> None:
        self.assertNotIn(
            "documentation", _protected("including documentation and help")
        )


class TestExtraSpans(unittest.TestCase):
    def test_an_emoji_is_protected(self) -> None:
        self.assertIn("🌐", _protected("ActivityPub Support 🌐 Seamlessly integrate"))

    def test_an_email_address_is_protected(self) -> None:
        self.assertIn("kevin@veen.world", _protected("Contact kevin@veen.world today"))


class TestMerge(unittest.TestCase):
    def test_spans_never_overlap(self) -> None:
        text = "Deploy `web-app-keycloak` next to Keycloak and Nextcloud 🌐"
        offsets = matches(text)

        self.assertEqual(offsets, sorted(offsets))
        for (_, end), (start, _) in pairwise(offsets):
            self.assertLessEqual(end, start)

    def test_a_backticked_name_is_claimed_once(self) -> None:
        text = "see `web-app-keycloak` for details"

        self.assertIn("`web-app-keycloak`", _protected(text))

    def test_a_name_stays_out_of_the_comparison_set(self) -> None:
        self.assertNotIn("Keycloak", protected_spans("Keycloak issues the token"))


class TestMissingNames(unittest.TestCase):
    def test_a_dropped_name_is_reported(self) -> None:
        lost = missing_names(
            "DNS resolver engines (Unbound, etc.)", "DNS-Engines (Ungebunden, usw.)"
        )

        self.assertEqual(lost, {"Unbound"})

    def test_a_kept_name_is_not_reported(self) -> None:
        lost = missing_names(
            "DNS resolver engines (Unbound, etc.)", "DNS-Engines (Unbound, usw.)"
        )

        self.assertEqual(lost, set())

    def test_a_german_compound_still_carries_the_name(self) -> None:
        lost = missing_names(
            "one Redis user per consumer", "ein Redis-Benutzer je Nutzer"
        )

        self.assertEqual(lost, set())

    def test_a_capital_the_source_did_not_have_is_not_a_loss(self) -> None:
        lost = missing_names("bundling shell extensions", "bündelt Shell-Erweiterungen")

        self.assertEqual(lost, set())

    def test_a_message_of_only_names_holds_no_words(self) -> None:
        self.assertFalse(has_words("web-app-keycloak"))

    def test_prose_still_holds_words(self) -> None:
        self.assertTrue(has_words("Deploy it behind the proxy"))

    def test_spans_are_offsets_into_the_text(self) -> None:
        text = "Deploy web-app-keycloak now"
        start, end = spans(text)[0]

        self.assertEqual(text[start:end], "web-app-keycloak")


if __name__ == "__main__":
    unittest.main()
