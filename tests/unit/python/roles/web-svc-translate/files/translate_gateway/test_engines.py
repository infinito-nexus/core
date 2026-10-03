"""One client reaches every backend that speaks the LibreTranslate API."""

from __future__ import annotations

import io
import json
import unittest
import unittest.mock

from . import ENGINES

LibreTranslateEngine = ENGINES.LibreTranslateEngine


def _answer(payload):
    return io.BytesIO(json.dumps(payload).encode())


class ServesTestCase(unittest.TestCase):
    def test_an_unknown_catalogue_reads_as_any_pair(self) -> None:
        engine = LibreTranslateEngine("alpha", "http://alpha:5000")

        self.assertTrue(engine.serves("de", "en"))
        self.assertTrue(engine.serves(None, "zh"))

    def test_a_declared_catalogue_is_honoured(self) -> None:
        engine = LibreTranslateEngine(
            "alpha", "http://alpha:5000", languages=[("de", "en")]
        )

        self.assertTrue(engine.serves("de", "en"))
        self.assertFalse(engine.serves("de", "fr"))

    def test_an_absent_source_is_looked_up_as_auto(self) -> None:
        engine = LibreTranslateEngine(
            "alpha", "http://alpha:5000", languages=[("auto", "en")]
        )

        self.assertTrue(engine.serves(None, "en"))


class PairsTestCase(unittest.TestCase):
    def test_a_declared_catalogue_is_readable_for_the_languages_route(self) -> None:
        engine = LibreTranslateEngine(
            "alpha", "http://alpha:5000", languages=[("de", "en"), ("en", "de")]
        )

        self.assertEqual(engine.pairs, frozenset({("de", "en"), ("en", "de")}))

    def test_a_backend_without_a_catalogue_contributes_nothing(self) -> None:
        """It still serves every pair; it just cannot be listed."""
        engine = LibreTranslateEngine("alpha", "http://alpha:5000")

        self.assertEqual(engine.pairs, frozenset())
        self.assertTrue(engine.serves("de", "en"))


class TranslateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = LibreTranslateEngine("alpha", "http://alpha:5000/")

    def _call(self, reply, **kwargs):
        with unittest.mock.patch.object(ENGINES.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = _answer(reply)
            result = self.engine.translate(
                kwargs.get("source", "de"), "en", kwargs.get("text", "Haus")
            )
        self.request = urlopen.call_args[0][0]
        self.sent = json.loads(self.request.data)
        return result

    def test_it_returns_the_translated_text(self) -> None:
        self.assertEqual(self._call({"translatedText": "House"}), "House")

    def test_the_trailing_slash_of_the_base_url_is_not_doubled(self) -> None:
        self._call({"translatedText": "House"})

        self.assertEqual(self.request.full_url, "http://alpha:5000/translate")

    def test_an_absent_source_is_sent_as_auto(self) -> None:
        self._call({"translatedText": "House"}, source=None)

        self.assertEqual(self.sent["source"], "auto")

    def test_an_answer_without_a_translation_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._call({"error": "model not loaded"})

        self.assertIn("alpha", str(caught.exception))

    def test_an_empty_translation_is_refused_rather_than_served(self) -> None:
        with self.assertRaises(ValueError):
            self._call({"translatedText": ""})

    def test_the_api_key_travels_only_when_configured(self) -> None:
        self._call({"translatedText": "House"})
        self.assertNotIn("api_key", self.sent)

        self.engine = LibreTranslateEngine("alpha", "http://alpha:5000", api_key="k")
        self._call({"translatedText": "House"})
        self.assertEqual(self.sent["api_key"], "k")


class DetectTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = LibreTranslateEngine("alpha", "http://alpha:5000")

    def _call(self, reply):
        with unittest.mock.patch.object(ENGINES.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = _answer(reply)
            return self.engine.detect("Haus")

    def test_the_first_candidate_wins(self) -> None:
        self.assertEqual(
            self._call([{"language": "de", "confidence": 0.9}, {"language": "nl"}]),
            "de",
        )

    def test_no_candidate_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._call([])

    def test_a_non_list_answer_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._call({"language": "de"})


class ChatModelEngineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ENGINES.ChatModelEngine(
            "ollama", "http://litellm:4000/v1/", "llama3.2:1b", api_key="sk-virtual"
        )

    def _call(self, payload):
        with unittest.mock.patch.object(ENGINES.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = _answer(payload)
            answer = self.engine.translate("en", "de", "House")
            self.request = urlopen.call_args.args[0]
        return answer

    def test_the_completion_is_the_translation(self) -> None:
        answer = self._call({"choices": [{"message": {"content": " Haus "}}]})

        self.assertEqual(answer, "Haus")

    def test_the_prompt_goes_to_the_model_gateway_with_its_virtual_key(self) -> None:
        self._call({"choices": [{"message": {"content": "Haus"}}]})

        self.assertEqual(
            self.request.full_url, "http://litellm:4000/v1/chat/completions"
        )
        self.assertEqual(self.request.get_header("Authorization"), "Bearer sk-virtual")
        body = json.loads(self.request.data)
        self.assertEqual(body["model"], "llama3.2:1b")
        self.assertIn("House", body["messages"][0]["content"])
        self.assertIn("de", body["messages"][0]["content"])

    def test_the_protected_terms_are_handed_to_the_model(self) -> None:
        with unittest.mock.patch.object(ENGINES.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = _answer(
                {"choices": [{"message": {"content": "Haus"}}]}
            )
            self.engine.translate("en", "de", "House", ("Nextcloud", "Infinito.Nexus"))
            request = urlopen.call_args.args[0]

        prompt = json.loads(request.data)["messages"][0]["content"]
        self.assertIn("Nextcloud, Infinito.Nexus", prompt)

    def test_a_request_without_terms_carries_no_glossary_line(self) -> None:
        self._call({"choices": [{"message": {"content": "Haus"}}]})

        prompt = json.loads(self.request.data)["messages"][0]["content"]
        self.assertNotIn("Keep these terms", prompt)

    def test_an_answer_without_a_completion_is_refused(self) -> None:
        for payload in ({"choices": []}, {"choices": [{"message": {"content": "  "}}]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self._call(payload)


if __name__ == "__main__":
    unittest.main()
