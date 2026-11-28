from __future__ import annotations

import asyncio
import json
import sys
import types
import unittest
import unittest.mock

from . import GATEWAY, _load

Gateway = GATEWAY.Gateway

JSON = "application/json"
FORM = "application/x-www-form-urlencoded"
OK = 200
NUMBER = (int, float)


class FakeApp:
    def __init__(self, title):
        self.title = title
        self.routes = {}

    def api_route(self, path, methods, **_options):
        def register(handler):
            for method in methods:
                self.routes[method, path] = handler
            return handler

        return register

    def post(self, path):
        return self.api_route(path, ["POST"])

    def get(self, path):
        return self.api_route(path, ["GET"])

    def exception_handler(self, _kind):
        return lambda handler: handler


class FakeJSONResponse:
    def __init__(self, content=None, status_code=OK):
        self.status_code = status_code
        self.body = json.dumps(content, allow_nan=False).encode()


class FakeForm:
    def __init__(self, pairs):
        self._pairs = pairs

    def keys(self):
        return dict(self._pairs).keys()

    def __getitem__(self, key):
        return dict(self._pairs)[key]

    def getlist(self, key):
        return [value for name, value in self._pairs if name == key]


class FakeRequest:
    def __init__(self, body, *, media=JSON):
        self.headers = {"content-type": media}
        self._body = body

    async def json(self):
        return self._body

    async def form(self):
        return FakeForm(self._body)


def _fastapi_stub():
    fastapi = types.ModuleType("fastapi")
    responses = types.ModuleType("fastapi.responses")
    fastapi.FastAPI = FakeApp
    fastapi.Request = FakeRequest
    responses.JSONResponse = FakeJSONResponse
    fastapi.responses = responses
    return {"fastapi": fastapi, "fastapi.responses": responses}


with unittest.mock.patch.dict(sys.modules, _fastapi_stub()):
    APP = _load("app")


class StubRouter:
    def __init__(self):
        self.formats = []

    async def translate(
        self, source, target, text, *, protected=(), fmt="text", exclude=()
    ):
        self.formats.append(fmt)
        return "alpha", f"[{target}] {text}"


class StubEngine:
    pairs = frozenset({("en", "de"), ("en", "fr"), ("de", "en")})

    def __init__(self):
        self.detects = "de"

    def detect(self, text):
        if isinstance(self.detects, Exception):
            raise self.detects
        return self.detects


class LibreTranslateShapes(unittest.TestCase):
    def assert_candidate(self, candidate):
        self.assertIsInstance(candidate, dict)
        self.assertIsInstance(candidate.get("language"), str)
        self.assertIsInstance(candidate.get("confidence"), NUMBER)
        self.assertNotIsInstance(candidate["confidence"], bool)

    def assert_translation(self, body, q, *, auto=False):
        self.assertIsInstance(body, dict)
        batch = isinstance(q, list)
        answers = body.get("translatedText")
        if batch:
            self.assertIsInstance(answers, list)
            self.assertEqual(len(answers), len(q))
            for answer in answers:
                self.assertIsInstance(answer, str)
        else:
            self.assertIsInstance(answers, str)
        if not auto:
            self.assertNotIn("detectedLanguage", body)
            return
        detected = body.get("detectedLanguage")
        if batch:
            self.assertIsInstance(detected, list)
            self.assertEqual(len(detected), len(q))
            for candidate in detected:
                self.assert_candidate(candidate)
        else:
            self.assert_candidate(detected)

    def assert_detection(self, body):
        self.assertIsInstance(body, list)
        self.assertTrue(body)
        for candidate in body:
            self.assert_candidate(candidate)

    def assert_catalogue(self, body):
        self.assertIsInstance(body, list)
        self.assertTrue(body)
        for language in body:
            self.assertIsInstance(language, dict)
            self.assertIsInstance(language.get("code"), str)
            self.assertIsInstance(language.get("name"), str)
            self.assertIsInstance(language.get("targets"), list)
            for target in language["targets"]:
                self.assertIsInstance(target, str)


class GatewayAppTestCase(LibreTranslateShapes):
    def setUp(self) -> None:
        self.router = StubRouter()
        self.engine = StubEngine()
        self.app = APP.create_app(Gateway(self.router), {"alpha": self.engine})

    def post(self, path, body, *, media=JSON):
        handler = self.app.routes["POST", path]
        response = asyncio.run(handler(FakeRequest(body, media=media)))
        return response.status_code, json.loads(response.body)

    def get(self, path):
        response = asyncio.run(self.app.routes["GET", path]())
        return response.status_code, json.loads(response.body)


class TranslateTestCase(GatewayAppTestCase):
    def test_a_string_q_is_answered_with_a_string(self) -> None:
        status, body = self.post(
            "/translate",
            {
                "q": "House",
                "source": "en",
                "target": "de",
                "format": "text",
                "api_key": "k",
            },
        )

        self.assertEqual(status, OK)
        self.assert_translation(body, "House")
        self.assertEqual(body["translatedText"], "[de] House")

    def test_a_list_q_is_answered_with_a_list_in_order(self) -> None:
        q = ["House", "Tree"]
        status, body = self.post(
            "/translate", {"q": q, "source": "en", "target": "de", "format": "text"}
        )

        self.assertEqual(status, OK)
        self.assert_translation(body, q)
        self.assertEqual(body["translatedText"], ["[de] House", "[de] Tree"])

    def test_an_auto_source_reports_the_detected_language(self) -> None:
        status, body = self.post(
            "/translate", {"q": "Haus", "source": "auto", "target": "en"}
        )

        self.assertEqual(status, OK)
        self.assert_translation(body, "Haus", auto=True)
        self.assertEqual(body["detectedLanguage"]["language"], "de")

    def test_an_auto_source_batch_reports_one_language_per_string(self) -> None:
        q = ["Haus", "Baum", "Garten"]
        status, body = self.post(
            "/translate", {"q": q, "source": "auto", "target": "en"}
        )

        self.assertEqual(status, OK)
        self.assert_translation(body, q, auto=True)

    def test_a_failing_detector_still_answers_the_translation(self) -> None:
        self.engine.detects = OSError("detector unreachable")

        status, body = self.post(
            "/translate", {"q": "Haus", "source": "auto", "target": "en"}
        )

        self.assertEqual(status, OK)
        self.assertEqual(body["translatedText"], "[en] Haus")
        self.assertNotIn("detectedLanguage", body)

    def test_the_format_reaches_the_engines(self) -> None:
        self.post(
            "/translate",
            {"q": "<b>House</b>", "source": "en", "target": "de", "format": "html"},
        )

        self.assertEqual(self.router.formats, ["html"])

    def test_a_form_post_repeating_q_is_a_batch(self) -> None:
        pairs = [
            ("q", "House"),
            ("q", "Tree"),
            ("source", "en"),
            ("target", "de"),
            ("format", "text"),
        ]
        status, body = self.post("/translate", pairs, media=FORM)

        self.assertEqual(status, OK)
        self.assert_translation(body, ["House", "Tree"])

    def test_the_shape_check_refuses_a_missing_translation(self) -> None:
        with self.assertRaises(self.failureException):
            self.assert_translation({"engine": "alpha"}, "House")

    def test_the_shape_check_refuses_a_string_for_a_batch(self) -> None:
        with self.assertRaises(self.failureException):
            self.assert_translation({"translatedText": "[de] House"}, ["House"])

    def test_the_shape_check_refuses_an_auto_answer_without_detection(self) -> None:
        with self.assertRaises(self.failureException):
            self.assert_translation({"translatedText": "House"}, "Haus", auto=True)


class DetectTestCase(GatewayAppTestCase):
    def test_detect_answers_a_list_of_candidates(self) -> None:
        status, body = self.post(
            "/detect", {"q": "Dies ist ein deutscher Satz.", "api_key": "k"}
        )

        self.assertEqual(status, OK)
        self.assert_detection(body)
        self.assertEqual(body[0]["language"], "de")

    def test_the_shape_check_refuses_a_candidate_without_confidence(self) -> None:
        with self.assertRaises(self.failureException):
            self.assert_detection([{"language": "de"}])

    def test_the_shape_check_refuses_a_textual_confidence(self) -> None:
        with self.assertRaises(self.failureException):
            self.assert_detection([{"language": "de", "confidence": "high"}])


class LanguagesTestCase(GatewayAppTestCase):
    def test_languages_answers_code_name_and_targets(self) -> None:
        status, body = self.get("/languages")

        self.assertEqual(status, OK)
        self.assert_catalogue(body)
        self.assertEqual(
            {entry["code"]: entry["targets"] for entry in body},
            {"de": ["en"], "en": ["de", "fr"]},
        )

    def test_the_shape_check_refuses_an_entry_without_a_name(self) -> None:
        with self.assertRaises(self.failureException):
            self.assert_catalogue([{"code": "en", "targets": ["de"]}])

    def test_the_shape_check_refuses_targets_that_are_not_a_list(self) -> None:
        with self.assertRaises(self.failureException):
            self.assert_catalogue([{"code": "en", "name": "en", "targets": "de"}])


if __name__ == "__main__":
    unittest.main()
