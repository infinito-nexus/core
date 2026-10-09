"""Unit tests for the on-disk view of the built sites.

``Sites`` is a mixin with no life of its own, so every case here drives it
through :class:`Library`, on the fixture its sibling module owns.
"""

from __future__ import annotations

import json
import unittest

from .test_library import LibraryFixture


class SitesFixture(LibraryFixture):
    def _publish(self, version: str, code: str | None = None) -> None:
        parent = self.library.translations / version / code if code else None
        root = parent or self.library.sites / version
        (root / "html").mkdir(parents=True)
        (root / "html" / "index.html").write_text("<p>ok</p>", encoding="utf-8")
        (root / "ref").write_text("deadbeef", encoding="utf-8")

    def _index(self, version: str, payload: object) -> None:
        directory = self.library.translations / version
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "languages.json").write_text(json.dumps(payload), encoding="utf-8")


class TestServable(SitesFixture, unittest.TestCase):
    def test_a_version_without_an_index_page_is_not_servable(self) -> None:
        self.assertFalse(self.library.servable("latest"))
        self.assertEqual(self.library.built_ref("latest"), "")

    def test_a_published_version_reports_its_ref(self) -> None:
        self._publish("latest")

        self.assertTrue(self.library.servable("latest"))
        self.assertEqual(self.library.built_ref("latest"), "deadbeef")

    def test_a_translation_is_tracked_per_code(self) -> None:
        self._publish("latest", "de")

        self.assertTrue(self.library.translation_servable("latest", "de"))
        self.assertFalse(self.library.translation_servable("latest", "fr"))
        self.assertEqual(self.library.translation_ref("latest", "de"), "deadbeef")
        self.assertEqual(self.library.translation_ref("latest", "fr"), "")


class TestLanguageIndex(SitesFixture, unittest.TestCase):
    def test_a_missing_index_counts_as_current(self) -> None:
        self.assertTrue(self.library._language_index_is_current("latest"))
        self.assertEqual(self.library.languages("latest"), ({}, []))

    def test_the_old_flat_shape_is_read_as_known_only(self) -> None:
        self._index("latest", {"de": "Deutsch"})

        self.assertEqual(self.library.languages("latest"), ({"de": "Deutsch"}, []))
        self.assertFalse(self.library.translates("latest", "de"))
        self.assertFalse(self.library._language_index_is_current("latest"))

    def test_the_split_shape_carries_the_translated_codes(self) -> None:
        self._index("latest", {"known": {"de": "Deutsch"}, "translated": ["de"]})
        self._publish("latest", "de")

        self.assertEqual(self.library.languages("latest"), ({"de": "Deutsch"}, ["de"]))
        self.assertTrue(self.library.translates("latest", "de"))
        self.assertTrue(self.library._language_index_is_current("latest"))

    def test_a_corrupt_index_is_neither_current_nor_readable(self) -> None:
        directory = self.library.translations / "latest"
        directory.mkdir(parents=True)
        (directory / "languages.json").write_text("{not json", encoding="utf-8")

        self.assertFalse(self.library._language_index_is_current("latest"))
        self.assertEqual(self.library.languages("latest"), ({}, []))


class TestResolve(SitesFixture, unittest.TestCase):
    def test_a_directory_resolves_to_its_index_page(self) -> None:
        self._publish("latest")

        self.assertEqual(
            self.library.resolve("latest", ""),
            self.library.sites / "latest" / "html" / "index.html",
        )

    def test_a_path_escaping_the_site_resolves_to_nothing(self) -> None:
        self._publish("latest")

        self.assertIsNone(self.library.resolve("latest", "../../etc/passwd"))

    def test_a_missing_file_resolves_to_nothing(self) -> None:
        self._publish("latest")

        self.assertIsNone(self.library.resolve("latest", "absent.html"))

    def test_a_translation_resolves_inside_its_own_site(self) -> None:
        self._publish("latest", "de")

        self.assertEqual(
            self.library.resolve_translation("latest", "de", ""),
            self.library.translations / "latest" / "de" / "html" / "index.html",
        )


if __name__ == "__main__":
    unittest.main()
