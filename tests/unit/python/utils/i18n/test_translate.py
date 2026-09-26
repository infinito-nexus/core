import json
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from babel.messages.catalog import Catalog

from utils.annotations.suppress import is_suppressed_at
from utils.i18n.catalog import (
    ENGINE,
    MACHINE_TRANSLATION,
    REFUSAL_PREFIX,
    REJECTED_PREFIX,
    TRANSLATION_REFUSED,
    build_template,
    merge,
    render,
)
from utils.i18n.libretranslate import LibreTranslate
from utils.i18n.placeholders import Rejected
from utils.i18n.translate import URL_SUPPRESSION, apply, damaged, pending, retry

TOKEN = re.compile(r'<x id="\d+"></x>')


class FakeLibreTranslate(BaseHTTPRequestHandler):
    """German by prefix; drops every token of a message containing ``lossy``."""

    requests: ClassVar[list[dict]] = []

    def log_message(self, *args):
        return

    def _reply(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply([{"code": "en", "targets": ["de", "fr"]}])

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLibreTranslate.requests.append(payload)
        translated = [
            TOKEN.sub("", f"DE {text}") if "lossy" in text else f"DE {text}"
            for text in payload["q"]
        ]
        self._reply({"translatedText": translated})


class TestTranslate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLibreTranslate)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.client = LibreTranslate(f"http://127.0.0.1:{cls.server.server_port}", 2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeLibreTranslate.requests.clear()

    def test_waits_for_offered_languages(self):
        self.client.wait(["de", "fr"], timeout=1)

        with self.assertRaises(TimeoutError):
            self.client.wait(["xx"], timeout=0)

    def test_requests_html_from_english_into_the_target(self):
        self.assertEqual(self.client.translate(["Hello"], "de").values, ["DE Hello"])
        self.assertEqual(
            {
                key: FakeLibreTranslate.requests[0][key]
                for key in ("source", "target", "format")
            },
            {"source": "en", "target": "de", "format": "html"},
        )

    def test_rules_for_human_fuzzy_empty_and_damaged_entries(self):
        catalog = merge(
            build_template(
                [
                    ("human", "Kept by a person"),
                    ("fuzzy", "Changed source"),
                    ("empty", "New source"),
                    ("lossy", "lossy {count} items"),
                ],
                "core",
            ),
            None,
            "de",
        )
        catalog.get("Kept by a person", context="human").string = "Von Hand"
        changed = catalog.get("Changed source", context="fuzzy")
        changed.string = "Veraltet"
        changed.flags.add("fuzzy")

        todo = pending(catalog)
        discarded = apply(
            todo, self.client.translate([m.id for m in todo], "de").values
        )

        human = catalog.get("Kept by a person", context="human")
        self.assertEqual((human.string, human.user_comments), ("Von Hand", []))
        self.assertEqual(changed.string, "DE Changed source")
        self.assertFalse(changed.fuzzy)
        self.assertEqual(changed.user_comments, [MACHINE_TRANSLATION])
        fresh = catalog.get("New source", context="empty")
        self.assertEqual(
            (fresh.string, fresh.user_comments),
            ("DE New source", [MACHINE_TRANSLATION]),
        )
        self.assertEqual(discarded, 1)
        lossy = catalog.get("lossy {count} items", context="lossy")
        self.assertFalse(lossy.string)
        self.assertEqual(
            lossy.user_comments,
            [
                f"{REFUSAL_PREFIX} {ENGINE} lost-token",
                URL_SUPPRESSION,
                f"{REJECTED_PREFIX} DE lossy items",
            ],
        )
        self.assertNotIn(lossy, pending(catalog))


class TestRefusalIsRemembered(unittest.TestCase):
    """A refusal is deterministic for an unchanged source, so it is recorded.

    Without the mark every run spends a masking pass, a request and an
    inference to reach the same verdict: 34 languages produced 185 requests
    and no translation before this landed.
    """

    def _entry(self, comments: list[str] | None = None):
        catalog = Catalog(locale="de")
        catalog.add("lossy {count} items", "", context="lossy")
        message = catalog.get("lossy {count} items", context="lossy")
        message.user_comments = list(comments or [])
        return catalog, message

    def test_a_refused_entry_is_not_offered_again(self):
        catalog, message = self._entry([TRANSLATION_REFUSED])

        self.assertNotIn(message, pending(catalog))

    def test_an_entry_without_the_mark_stays_pending(self):
        catalog, message = self._entry()

        self.assertIn(message, pending(catalog))

    def test_the_mark_is_written_once(self):
        _, message = self._entry([TRANSLATION_REFUSED])

        apply([message], [None])

        self.assertEqual(message.user_comments, [TRANSLATION_REFUSED])

    def test_a_translation_that_lands_clears_the_mark(self):
        _, message = self._entry([TRANSLATION_REFUSED])

        apply([message], ["verlustig {count} Einträge"])

        self.assertEqual(message.user_comments, [MACHINE_TRANSLATION])
        self.assertEqual(message.string, "verlustig {count} Einträge")

    def test_retry_offers_the_entry_again(self):
        catalog, message = self._entry([MACHINE_TRANSLATION, TRANSLATION_REFUSED])

        cleared = retry(catalog)

        self.assertEqual(cleared, 1)
        self.assertEqual(message.user_comments, [MACHINE_TRANSLATION])
        self.assertIn(message, pending(catalog))

    def test_the_mark_names_the_engine_that_tried(self):
        _, message = self._entry()

        apply([message], [None])

        self.assertEqual(
            message.user_comments, [f"{REFUSAL_PREFIX} {ENGINE} damaged-span"]
        )

    def test_the_rejected_translation_stays_readable_beside_the_mark(self):
        _, message = self._entry()

        apply([message], [Rejected("verlustig Einträge", "protected-span")])

        self.assertEqual(
            message.user_comments,
            [
                f"{REFUSAL_PREFIX} {ENGINE} protected-span",
                URL_SUPPRESSION,
                f"{REJECTED_PREFIX} verlustig Einträge",
            ],
        )
        self.assertFalse(message.string)

    def test_the_catalog_carries_the_rejection_as_a_comment(self):
        catalog, message = self._entry()

        apply([message], [Rejected("verlustig Einträge", "protected-span")])
        written = render(catalog).decode("utf-8")

        self.assertIn(f"# {REJECTED_PREFIX} verlustig Einträge\n", written)
        self.assertNotIn('verlustig Einträge"', written)

    def test_a_mangled_link_in_a_rejection_is_not_probed(self):
        catalog, message = self._entry()

        apply(
            [message],
            [Rejected("Siehe [den Leitfaden]](https://gone.invalid/a)", "structure")],
        )
        lines = render(catalog).decode("utf-8").splitlines()
        quoted = next(
            number
            for number, line in enumerate(lines, start=1)
            if line.startswith(f"# {REJECTED_PREFIX}")
        )

        self.assertTrue(is_suppressed_at(lines, quoted, "url", mode="block-above"))

    def test_a_rejected_translation_never_spills_over_its_comment_line(self):
        _, message = self._entry()

        apply([message], [Rejected("erste Zeile\nzweite Zeile", "structure")])

        self.assertEqual(
            message.user_comments[2],
            f"{REJECTED_PREFIX} erste Zeile\\nzweite Zeile",
        )

    def test_a_second_rejection_replaces_the_first(self):
        _, message = self._entry()

        apply([message], [Rejected("erster Versuch", "structure")])
        apply([message], [Rejected("zweiter Versuch", "stutter")])

        self.assertEqual(
            message.user_comments,
            [
                f"{REFUSAL_PREFIX} {ENGINE} stutter",
                URL_SUPPRESSION,
                f"{REJECTED_PREFIX} zweiter Versuch",
            ],
        )

    def test_a_translation_that_lands_clears_the_quoted_rejection(self):
        _, message = self._entry()

        apply([message], [Rejected("verlustig Einträge", "protected-span")])
        apply([message], ["verlustig {count} Einträge"])

        self.assertEqual(message.user_comments, [MACHINE_TRANSLATION])

    def test_a_suppression_the_source_carries_survives_the_cleanup(self):
        """Sphinx hands a source comment to the catalog; it is not ours to drop."""
        _, message = self._entry([URL_SUPPRESSION])

        apply([message], [Rejected("verlustig Einträge", "protected-span")])
        apply([message], ["verlustig {count} Einträge"])

        self.assertEqual(message.user_comments, [URL_SUPPRESSION, MACHINE_TRANSLATION])

    def test_a_refusal_from_another_engine_counts_and_clears(self):
        """The mark is matched by prefix, not by the engine this run uses."""
        catalog, message = self._entry([f"{REFUSAL_PREFIX} someone-else damaged-span"])

        self.assertNotIn(message, pending(catalog))
        self.assertEqual(retry(catalog), 1)
        self.assertIn(message, pending(catalog))


class TestDamagedMarkup(unittest.TestCase):
    """A bracket added or dropped beside a protected span leaves every span intact."""

    def _catalog(self, source: str, translation: str):
        catalog = Catalog(locale="de")
        catalog.add(source, translation)
        return catalog

    def test_an_added_bracket_is_damage(self):
        catalog = self._catalog(
            "See [the guide](docs/guide.md) first.",
            "Siehe [den Leitfaden]](docs/guide.md) zuerst.",
        )

        self.assertEqual(len(damaged(catalog)), 1)

    def test_a_dropped_bracket_is_damage(self):
        catalog = self._catalog(
            "![Logo](assets/img/logo.png)",
            "!Logo](assets/img/logo.png)",
        )

        self.assertEqual(len(damaged(catalog)), 1)

    def test_an_intact_translation_is_not_damage(self):
        catalog = self._catalog(
            "See [the guide](docs/guide.md) first.",
            "Siehe [den Leitfaden](docs/guide.md) zuerst.",
        )

        self.assertEqual(damaged(catalog), [])


if __name__ == "__main__":
    unittest.main()
