import json
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from babel.messages.catalog import Catalog

from utils.i18n.catalog import MACHINE_TRANSLATION, build_template, merge
from utils.i18n.libretranslate import LibreTranslate
from utils.i18n.translate import apply, damaged, pending

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
        self.assertFalse(catalog.get("lossy {count} items", context="lossy").string)


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
