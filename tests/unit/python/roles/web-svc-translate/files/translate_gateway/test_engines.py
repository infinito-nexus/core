"""The three backend protocols, each held to the interface the router calls."""

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
    def test_an_unreachable_catalogue_reads_as_any_pair(self) -> None:
        engine = LibreTranslateEngine("alpha", "http://alpha:5000")

        with unittest.mock.patch.object(engine, "catalogue", side_effect=OSError):
            self.assertTrue(engine.serves("de", "en"))
            self.assertTrue(engine.serves(None, "zh"))

    def test_the_backend_catalogue_binds_when_none_is_declared(self) -> None:
        """The engine's own ``/languages`` is what the router must honour.

        ``serves`` used to answer True for every pair here, so a language
        the engine holds no model for was routed to it and answered with
        HTTP 400 instead of falling through to the next backend. Declaring
        the pairs in the role instead carried a second copy that went stale:
        the engine reports ``zh-Hans`` where the role's list says ``zh``.
        """
        engine = LibreTranslateEngine("alpha", "http://alpha:5000")
        reported = {("en", "de"), ("en", "zh-Hans"), ("de", "en")}

        with unittest.mock.patch.object(
            engine, "catalogue", return_value=reported
        ) as read:
            self.assertTrue(engine.serves("en", "zh-Hans"))
            self.assertFalse(engine.serves("en", "aa"))
            self.assertFalse(engine.serves("en", "zh"))
        read.assert_called_once()

    def test_an_absent_source_matches_any_declared_target(self) -> None:
        engine = LibreTranslateEngine("alpha", "http://alpha:5000")

        with unittest.mock.patch.object(
            engine, "catalogue", return_value={("en", "de")}
        ):
            self.assertTrue(engine.serves(None, "de"))
            self.assertTrue(engine.serves("auto", "de"))
            self.assertFalse(engine.serves("auto", "aa"))

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

    def test_the_scaffolding_a_small_model_adds_is_not_translated_text(self) -> None:
        answer = self._call(
            {"choices": [{"message": {"content": "House\nGerman: Haus"}}]}
        )

        self.assertEqual(answer, "Haus")

    def test_an_answer_that_is_only_scaffolding_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._call({"choices": [{"message": {"content": "House"}}]})


class NllbEngineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ENGINES.NllbEngine("nllb", "http://nllb-engine:5060/")

    def _call(self, payload, **kwargs):
        with unittest.mock.patch.object(ENGINES.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = _answer(payload)
            answer = self.engine.translate(
                kwargs.get("source", "en"),
                kwargs.get("target", "be"),
                "House",
                (),
                kwargs.get("fmt", "text"),
            )
            self.request = urlopen.call_args.args[0]
        return answer

    def test_the_rendering_is_the_translation(self) -> None:
        self.assertEqual(self._call({"translation": " Дом "}), "Дом")

    def test_the_languages_travel_as_flores_codes(self) -> None:
        self._call({"translation": "Дом"})

        self.assertEqual(self.request.full_url, "http://nllb-engine:5060/translate")
        body = json.loads(self.request.data)
        self.assertEqual(body["source"], "eng_Latn")
        self.assertEqual(body["target"], "bel_Cyrl")
        self.assertEqual(body["text"], "House")

    def test_a_language_the_model_has_no_code_for_is_refused(self) -> None:
        """Refused here rather than sent, which is the whole point of the engine.

        The chat backend answered Abkhazian with Polish because nothing
        stopped the request from reaching a model that does not speak it.
        """
        with self.assertRaises(ValueError) as caught:
            self._call({"translation": "x"}, target="ab")

        self.assertIn("ab", str(caught.exception))

    def test_an_html_payload_is_refused_rather_than_mangled(self) -> None:
        with self.assertRaises(ValueError):
            self._call({"translation": "Дом"}, fmt="html")

    def test_an_answer_without_a_translation_is_refused(self) -> None:
        for payload in ({}, {"translation": "   "}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self._call(payload)


class NllbServesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ENGINES.NllbEngine("nllb", "http://nllb-engine:5060")

    def test_the_derived_catalogue_covers_what_the_model_carries(self) -> None:
        self.assertTrue(self.engine.serves("en", "be"))
        self.assertTrue(self.engine.serves("de", "am"))
        self.assertTrue(self.engine.serves("be", "en"))

    def test_a_language_outside_the_mapping_is_not_served(self) -> None:
        self.assertFalse(self.engine.serves("en", "ab"))
        self.assertFalse(self.engine.serves("av", "en"))

    def test_an_undeclared_source_is_refused_because_nllb_cannot_detect(self) -> None:
        self.assertFalse(self.engine.serves(None, "de"))
        self.assertFalse(self.engine.serves("auto", "de"))

    def test_a_declared_catalogue_narrows_the_derived_one(self) -> None:
        engine = ENGINES.NllbEngine(
            "nllb", "http://nllb-engine:5060", languages=[("en", "de")]
        )

        self.assertTrue(engine.serves("en", "de"))
        self.assertFalse(engine.serves("en", "be"))
        self.assertEqual(engine.pairs, frozenset({("en", "de")}))

    def test_the_catalogue_is_answered_without_reaching_the_server(self) -> None:
        """The mapping is the same on every host, so there is nothing to ask."""
        with unittest.mock.patch.object(ENGINES.urllib.request, "urlopen") as urlopen:
            catalogue = self.engine.catalogue()

        urlopen.assert_not_called()
        self.assertIn(("en", "be"), catalogue)


class CleanTestCase(unittest.TestCase):
    def test_the_markers_the_prompt_set_are_dropped(self) -> None:
        self.assertEqual(ENGINES.clean("---\nHaus\n---", "House"), "Haus")

    def test_an_echoed_source_line_is_dropped(self) -> None:
        self.assertEqual(ENGINES.clean("House\nHaus", "House"), "Haus")

    def test_a_language_label_is_dropped_from_a_scaffolded_answer(self) -> None:
        self.assertEqual(
            ENGINES.clean("House\nAfrikaans: Die huis", "House"), "Die huis"
        )

    def test_a_colon_in_a_clean_answer_is_not_read_as_a_label(self) -> None:
        self.assertEqual(
            ENGINES.clean("Hinweis: Das Haus", "House"), "Hinweis: Das Haus"
        )

    def test_a_non_latin_rendering_keeps_every_character(self) -> None:
        self.assertEqual(ENGINES.clean("дом", "House"), "дом")

    def test_a_clean_multi_line_translation_survives(self) -> None:
        self.assertEqual(ENGINES.clean("Haus\nHof", "House"), "Haus\nHof")


if __name__ == "__main__":
    unittest.main()
