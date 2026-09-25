"""Unit tests for the build machinery split out of ``library.py``.

``Builder`` is a mixin with no life of its own, so every case here drives it
through :class:`Library`, on the fixture its sibling module owns.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from utils.cache.files import read_text

from .test_library import LibraryFixture, _commit, builder, library


class TestBuilder(LibraryFixture, unittest.TestCase):
    def test_latest_is_built_from_the_last_commit(self) -> None:
        self.library.build("latest")

        self.assertEqual(self._site("latest", "version.txt"), "three")
        self.assertEqual(self._site("latest", "environment.txt"), "1 latest")
        self.assertEqual(self.library.built_ref("latest"), self.library.refs()[0])
        entry = self._state(self.library, "latest")
        self.assertEqual((entry["state"], entry["progress"]), ("ready", 100))
        self.assertEqual(self._state(self.library, "v1.0.0")["state"], "missing")
        self.assertIsNone(self.library.next_queued())
        self.assertFalse(list(self.library.scratch.iterdir()))

    def test_deployed_is_built_from_the_snapshot_and_stays_unlisted(self) -> None:
        snapshot = self.data / "snapshot"
        snapshot.mkdir(parents=True)
        (snapshot / "VERSION").write_text("working tree", encoding="utf-8")
        shelf = library.Library(str(self.repo), self.data, 1, self.package, snapshot)

        shelf.request("deployed")
        shelf.build("deployed")

        self.assertEqual(self._site("deployed", "version.txt"), "working tree")
        self.assertEqual(shelf.built_ref("deployed"), shelf.snapshot_ref())
        self.assertIn("deployed", shelf.versions())
        self.assertNotIn("deployed", [entry["name"] for entry in shelf.status()])
        shelf.request("deployed")
        self.assertFalse((shelf.queue / "deployed").exists())

    def _drain(self, limit=20):
        """Run the builder's dispatch until the queue empties.

        Args:
            limit: hard stop so a marker that never clears fails loudly.
        """
        drained = []
        for _ in range(limit):
            marker = self.library.next_queued()
            if marker is None:
                return drained
            drained.append(marker)
            version, separator, code = marker.partition(":")
            if separator:
                self.library.build_language(version, code)
            else:
                self.library.build(version)
        raise AssertionError(f"queue did not empty in {limit} steps, drained {drained}")

    def test_the_builder_drains_every_queued_language(self) -> None:
        (self.repo / "meta").mkdir()
        (self.repo / "meta" / "languages.yml").write_text(
            "en:\n  native: English\nde:\n  native: Deutsch\n"
            "fr:\n  native: Français\nit:\n  native: Italiano\n",
            encoding="utf-8",
        )
        for code in ("de", "fr", "it"):
            catalog = self.repo / "locale" / code / "LC_MESSAGES" / "docs.po"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(
                f'msgid ""\nmsgstr ""\n"Language: {code}\\n"\n\nmsgid "Hello"\nmsgstr "Hallo {code}"\n',
                encoding="utf-8",
            )
        _commit(self.repo, "three translations")
        self.library.fetch()
        self.library.build("latest")

        self.library.request("latest", "it")
        drained = self._drain()

        self.assertEqual(
            drained[0], "latest:it", "the requested language must run first"
        )
        self.assertEqual(sorted(drained), ["latest:de", "latest:fr", "latest:it"])
        self.assertEqual(self.library.languages("latest")[1], ["de", "fr", "it"])
        self.assertIsNone(self.library.next_queued())

    def test_a_translated_language_builds_its_site_on_request(self) -> None:
        (self.repo / "meta").mkdir()
        (self.repo / "meta" / "languages.yml").write_text(
            "en:\n  native: English\nde:\n  native: Deutsch\nfr:\n  native: Français\n",
            encoding="utf-8",
        )
        for code, translation in (("de", "Hallo"), ("fr", "")):
            catalog = self.repo / "locale" / code / "LC_MESSAGES" / "docs.po"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(
                f'msgid ""\nmsgstr ""\n"Language: {code}\\n"\n\nmsgid "Hello"\nmsgstr "{translation}"\n',
                encoding="utf-8",
            )
        _commit(self.repo, "translated")
        self.library.fetch()

        self.library.build("latest")

        known, built = self.library.languages("latest")
        self.assertEqual(sorted(known), ["de", "en", "fr"])
        self.assertEqual(built, [], "a version build must not prebuild any language")
        self.assertTrue(self.library.translates("latest", "de"))
        self.assertFalse(self.library.translates("latest", "fr"))
        self.assertTrue(
            (self.library.queue / "background" / "latest:de").exists(),
            "every translated language must stay queued for a background build",
        )
        self.assertFalse((self.library.queue / "background" / "latest:fr").exists())
        self.assertEqual(self.library.next_queued(), "latest:de")

        self.library.request("latest", "fr")
        self.assertFalse(
            (self.library.queue / "latest:fr").exists(),
            "an untranslated language must not enter the queue",
        )
        self.library.request("latest", "de")
        self.assertTrue((self.library.queue / "latest:de").exists())
        self.library.build_language("latest", "de")

        self.assertEqual(self.library.languages("latest")[1], ["de"])
        self.assertFalse((self.library.queue / "latest:de").exists())
        self.assertTrue(self.library.translation_servable("latest", "de"))
        page = self.library.resolve_translation("latest", "de", "docs/")
        self.assertEqual(read_text(str(page)), "docs")
        self.assertIsNone(
            self.library.resolve_translation("latest", "de", "../../etc/passwd")
        )

    def _translated_repo(self, *codes: str) -> None:
        (self.repo / "meta").mkdir()
        native = "en:\n  native: English\n" + "".join(
            f"{code}:\n  native: {code.upper()}\n" for code in codes
        )
        (self.repo / "meta" / "languages.yml").write_text(native, encoding="utf-8")
        for code in codes:
            catalog = self.repo / "locale" / code / "LC_MESSAGES" / "docs.po"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(
                f'msgid ""\nmsgstr ""\n"Language: {code}\\n"\n\nmsgid "Hi"\nmsgstr "Hallo"\n',
                encoding="utf-8",
            )

    def test_a_new_commit_rebuilds_the_translated_sites_too(self) -> None:
        self._translated_repo("de")
        _commit(self.repo, "first")
        self.library.fetch()
        self._drain()
        site = self.library.translations / "latest" / "de" / "html" / "version.txt"
        self.assertEqual(site.read_text(encoding="utf-8"), "first")  # nocheck: cache-read

        _commit(self.repo, "second")
        self.library.fetch()
        drained = self._drain()

        self.assertIn(
            "latest:de",
            drained,
            "a version rebuild must not leave its translated sites on the old commit",
        )
        self.assertEqual(self._site("latest", "version.txt"), "second")
        self.assertEqual(site.read_text(encoding="utf-8"), "second")  # nocheck: cache-read

    def test_a_failing_language_does_not_mark_the_version_failed(self) -> None:
        self._translated_repo("de")
        _commit(self.repo, "first")
        self.library.fetch()
        self.library.build("latest")
        self.assertEqual(self._state(self.library, "latest")["state"], "ready")

        with patch.object(
            builder.Builder, "_run", side_effect=OSError("sphinx died")
        ):
            self.library.build_language("latest", "de")

        self.assertEqual(
            self._state(self.library, "latest")["state"],
            "ready",
            "a language that fails must not report its version as failed",
        )
        self.assertTrue(self.library.servable("latest"))
        self.assertFalse(self.library.translation_servable("latest", "de"))

    def test_an_index_write_that_fails_leaves_the_version_unpublished(self) -> None:
        self._translated_repo("de")
        _commit(self.repo, "first")
        self.library.fetch()
        with patch.object(builder, "write_json", side_effect=OSError("full disk")):
            self.library.build("latest")

        self.assertFalse(
            self.library.servable("latest"),
            "publishing before the index write would re-queue the build forever",
        )

    def test_tag_is_built_from_its_own_commit_and_only_once(self) -> None:
        self.library.request("v1.0.0")
        self.library.build("v1.0.0")

        self.assertEqual(self._site("v1.0.0", "version.txt"), "one")
        self.library.request("v1.0.0")
        self.assertFalse((self.library.queue / "v1.0.0").exists())

    def test_failed_build_keeps_the_log_and_publishes_nothing(self) -> None:
        (self.repo / "BROKEN").write_text("x", encoding="utf-8")
        _commit(self.repo, "broken")
        self.library.fetch()

        self.library.build("latest")

        entry = self._state(self.library, "latest")
        self.assertEqual(entry["state"], "failed")
        self.assertIn("Sphinx error: broken source", entry["log"])
        self.assertFalse(self.library.servable("latest"))
        self.library.request("latest")
        self.assertEqual(self._state(self.library, "latest")["state"], "queued")


if __name__ == "__main__":
    unittest.main()
