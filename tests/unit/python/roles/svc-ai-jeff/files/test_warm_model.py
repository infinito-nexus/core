from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stderr
from typing import ClassVar, Self
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/svc-ai-jeff/files/python/warm_model.py"

ENVIRONMENT = {
    "JEFF_PORT": "8080",
    "JEFF_MODEL_ALIASES": "jev-latest,jev-older",
    "JEFF_API_KEYS": "sk-first-key,sk-second-key",
}


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def run_script(body: bytes) -> dict[str, object]:
    seen: dict[str, object] = {}

    def fake_urlopen(request: object, timeout: float | None = None) -> FakeResponse:
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["body"] = json.loads(request.data.decode())
        seen["timeout"] = timeout
        return FakeResponse(body)

    spec = importlib.util.spec_from_file_location("jeff_warm_model", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    with (
        patch.dict("os.environ", ENVIRONMENT, clear=False),
        patch("urllib.request.urlopen", fake_urlopen),
    ):
        spec.loader.exec_module(module)
    return seen


class TestJeffWarmModel(unittest.TestCase):
    """The router refuses to route when jeff misses its deadline, so the deploy
    pays the cold load instead of the first caller. That only holds when the
    warm-up reaches jeff and recognises a real answer.
    """

    ANSWERED: ClassVar[bytes] = b'{"answers": {"warmup": {"choice": "weather"}}}'

    def test_asks_jeff_on_its_own_loopback(self) -> None:
        seen = run_script(self.ANSWERED)
        self.assertEqual(seen["url"], "http://127.0.0.1:8080/v1/systemone")
        self.assertEqual(seen["method"], "POST")

    def test_takes_the_first_alias_and_the_first_key(self) -> None:
        seen = run_script(self.ANSWERED)
        self.assertEqual(seen["headers"]["authorization"], "Bearer sk-first-key")
        self.assertEqual(seen["body"]["model"], "jev-latest")

    def test_asks_a_choice_question_the_encoder_can_answer(self) -> None:
        question = run_script(self.ANSWERED)["body"]["questions"]["warmup"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(
            sorted(question["criteria"]),
            ["cooking", "weather"],
            "a choice needs labels to pick between, and the state names one of "
            "them, so an encoder that loaded has something to answer",
        )

    def test_waits_longer_than_the_router_would(self) -> None:
        self.assertGreater(
            run_script(self.ANSWERED)["timeout"],
            20,
            "the cold load is what overruns services.jeff.request_timeout, so a "
            "warm-up on that budget would time out exactly where the router did",
        )

    def test_an_answer_without_the_question_exits_non_zero(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            run_script(b'{"answers": {}}')
        self.assertEqual(
            caught.exception.code,
            1,
            "a 200 carrying no answer means the model did not decide, and "
            "reporting success there would hand the cold load back to the "
            "first caller",
        )


if __name__ == "__main__":
    unittest.main()
