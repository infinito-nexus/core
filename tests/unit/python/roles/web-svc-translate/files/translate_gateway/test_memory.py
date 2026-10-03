"""What Weblate is asked, and what counts as an answer."""

from __future__ import annotations

import unittest
from typing import ClassVar

from . import MEMORY

WeblateClient = MEMORY.WeblateClient
WeblateGlossary = MEMORY.WeblateGlossary
WeblateMemory = MEMORY.WeblateMemory
APPROVED = MEMORY.APPROVED


class FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.asked: list[tuple] = []

    def get(self, path, params=None):
        self.asked.append((path, params))
        return self.answers.get(path, {})


class ReviewedStringTestCase(unittest.TestCase):
    def test_an_approved_unit_answers_with_its_target(self) -> None:
        client = FakeClient(
            {
                "units/": {
                    "results": [
                        {"state": APPROVED, "target": ["Haus"]},
                    ]
                }
            }
        )

        self.assertEqual(WeblateMemory(client).reviewed("en", "de", "House"), "Haus")

    def test_a_unit_below_approved_is_not_a_reviewed_string(self) -> None:
        client = FakeClient(
            {"units/": {"results": [{"state": 20, "target": ["Haus"]}]}}
        )

        self.assertIsNone(WeblateMemory(client).reviewed("en", "de", "House"))

    def test_an_approved_unit_without_a_target_is_skipped(self) -> None:
        client = FakeClient(
            {
                "units/": {
                    "results": [
                        {"state": APPROVED, "target": ["  "]},
                        {"state": APPROVED, "target": ["Haus"]},
                    ]
                }
            }
        )

        self.assertEqual(WeblateMemory(client).reviewed("en", "de", "House"), "Haus")

    def test_the_query_asks_for_the_exact_source_in_the_target_language(self) -> None:
        client = FakeClient({"units/": {"results": []}})

        WeblateMemory(client).reviewed("en", "de", 'a "quoted" string')

        _path, params = client.asked[0]
        self.assertIn('source:="a \\"quoted\\" string"', params["q"])
        self.assertIn("language:de", params["q"])
        self.assertIn("state:>=approved", params["q"])
        self.assertIn("source_language:en", params["q"])

    def test_an_undeclared_source_language_is_left_out_of_the_query(self) -> None:
        client = FakeClient({"units/": {"results": []}})

        WeblateMemory(client).reviewed(None, "de", "House")

        self.assertNotIn("source_language", client.asked[0][1]["q"])


class GlossaryTestCase(unittest.TestCase):
    ANSWERS: ClassVar[dict] = {
        "projects/infinito/components/": {
            "results": [
                {"slug": "prose", "is_glossary": False},
                {"slug": "terms", "is_glossary": True},
            ]
        },
        "translations/infinito/terms/de/units/": {
            "results": [
                {"source": ["Nextcloud"]},
                {"source": ["onion"]},
                {"source": ["  "]},
            ]
        },
    }

    def test_only_the_terms_the_text_carries_are_protected(self) -> None:
        glossary = WeblateGlossary(FakeClient(self.ANSWERS), "infinito")

        self.assertEqual(
            glossary.terms("de", "Our Nextcloud is reachable."), ("Nextcloud",)
        )

    def test_a_non_glossary_component_is_never_read(self) -> None:
        client = FakeClient(self.ANSWERS)

        WeblateGlossary(client, "infinito").terms("de", "Nextcloud")

        self.assertNotIn(
            "translations/infinito/prose/de/units/", [path for path, _ in client.asked]
        )

    def test_the_term_list_is_read_once_per_language(self) -> None:
        client = FakeClient(self.ANSWERS)
        glossary = WeblateGlossary(client, "infinito")

        glossary.terms("de", "Nextcloud")
        glossary.terms("de", "onion")

        self.assertEqual(
            len([path for path, _ in client.asked if path.endswith("units/")]), 1
        )


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class ClientTestCase(unittest.TestCase):
    def test_the_request_carries_weblates_own_token_scheme_and_path(self) -> None:
        sent = []

        def urlopen(request, timeout=None):
            sent.append((request, timeout))
            return _Response(b"{}")

        original = MEMORY.urllib.request.urlopen
        MEMORY.urllib.request.urlopen = urlopen
        try:
            WeblateClient("https://translate.example.org/", "wlu_secret").get(
                "units/", {"q": "source:=x"}
            )
        finally:
            MEMORY.urllib.request.urlopen = original

        request, _timeout = sent[0]
        self.assertEqual(
            request.full_url,
            "https://translate.example.org/api/units/?q=source%3A%3Dx",
        )
        self.assertEqual(request.get_header("Authorization"), "Token wlu_secret")


if __name__ == "__main__":
    unittest.main()
