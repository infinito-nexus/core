"""Two requests share a signature when a verdict on one applies to the other."""

from __future__ import annotations

import unittest

from . import SIGNATURE

cache_key = SIGNATURE.cache_key
carries_markup = SIGNATURE.carries_markup
length_class = SIGNATURE.length_class
signature = SIGNATURE.signature


class LengthClassTestCase(unittest.TestCase):
    def test_nearby_lengths_fall_in_one_bucket(self) -> None:
        self.assertEqual(length_class("x" * 300), length_class("x" * 310))

    def test_a_bucket_boundary_separates_them(self) -> None:
        self.assertNotEqual(length_class("x" * 256), length_class("x" * 257))

    def test_the_largest_bucket_is_open_ended(self) -> None:
        self.assertEqual(length_class("x" * 9000), length_class("x" * 90000))

    def test_an_empty_or_missing_text_is_the_smallest_bucket(self) -> None:
        self.assertEqual(length_class(""), length_class(None))


class MarkupTestCase(unittest.TestCase):
    def test_plain_prose_carries_none(self) -> None:
        self.assertFalse(carries_markup("Das Haus ist gross."))

    def test_an_html_tag_counts(self) -> None:
        self.assertTrue(carries_markup("Das <b>Haus</b>"))

    def test_an_entity_counts(self) -> None:
        self.assertTrue(carries_markup("Haus &amp; Hof"))

    def test_a_jinja_placeholder_counts(self) -> None:
        self.assertTrue(carries_markup("Hallo {{ name }}"))

    def test_a_markdown_link_counts(self) -> None:
        self.assertTrue(carries_markup("siehe [hier](https://example.org)"))


class SignatureTestCase(unittest.TestCase):
    def test_the_same_pair_and_shape_share_a_signature(self) -> None:
        self.assertEqual(
            signature("de", "en", "Das Haus"), signature("de", "en", "Der Hof")
        )

    def test_markup_separates_two_otherwise_equal_requests(self) -> None:
        self.assertNotEqual(
            signature("de", "en", "Das Haus"), signature("de", "en", "Das <b>Haus</b>")
        )

    def test_the_target_language_separates_them(self) -> None:
        self.assertNotEqual(
            signature("de", "en", "Haus"), signature("de", "fr", "Haus")
        )

    def test_an_absent_source_reads_as_auto(self) -> None:
        self.assertTrue(signature(None, "en", "Haus").startswith("auto:en:"))


class CacheKeyTestCase(unittest.TestCase):
    def test_the_same_request_on_one_engine_hits(self) -> None:
        self.assertEqual(
            cache_key("alpha", "de", "en", "Haus"),
            cache_key("alpha", "de", "en", "Haus"),
        )

    def test_another_engine_is_another_entry(self) -> None:
        self.assertNotEqual(
            cache_key("alpha", "de", "en", "Haus"),
            cache_key("beta", "de", "en", "Haus"),
        )

    def test_a_different_text_is_another_entry(self) -> None:
        self.assertNotEqual(
            cache_key("alpha", "de", "en", "Haus"),
            cache_key("alpha", "de", "en", "Hof"),
        )

    def test_the_text_itself_does_not_travel_in_the_key(self) -> None:
        self.assertNotIn("Haus", cache_key("alpha", "de", "en", "Haus"))

    def test_another_format_is_another_entry(self) -> None:
        self.assertNotEqual(
            cache_key("alpha", "de", "en", '<x id="0"></x>', "text"),
            cache_key("alpha", "de", "en", '<x id="0"></x>', "html"),
        )


if __name__ == "__main__":
    unittest.main()
