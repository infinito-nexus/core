from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from typing import Self
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/svc-ai-litellm/files/python/warm_model.py"

ENVIRONMENT = {
    "LITELLM_MK": "sk-master-key",
    "LITELLM_PORT": "4000",
    "LITELLM_MODEL": "smollm2:135m",
}


class FakeResponse:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return b'{"choices": []}'


def run_script() -> None:
    spec = importlib.util.spec_from_file_location("warm_model", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


class TestWarmModel(unittest.TestCase):
    def test_posts_a_minimal_completion_to_the_local_gateway(self) -> None:
        seen: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: float | None = None) -> FakeResponse:
            seen["url"] = request.full_url
            seen["method"] = request.get_method()
            seen["headers"] = {k.lower(): v for k, v in request.header_items()}
            seen["body"] = json.loads(request.data.decode())
            seen["timeout"] = timeout
            return FakeResponse()

        with (
            patch.dict("os.environ", ENVIRONMENT, clear=False),
            patch("urllib.request.urlopen", fake_urlopen),
            redirect_stdout(io.StringIO()) as captured,
        ):
            run_script()

        self.assertEqual(seen["url"], "http://127.0.0.1:4000/v1/chat/completions")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["headers"]["authorization"], "Bearer sk-master-key")
        self.assertEqual(seen["headers"]["content-type"], "application/json")
        self.assertEqual(seen["body"]["model"], "smollm2:135m")
        self.assertEqual(seen["body"]["max_tokens"], 1)
        self.assertIn("WARMED smollm2:135m", captured.getvalue())

    def test_waits_far_longer_than_a_proxy_read_timeout(self) -> None:
        seen: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: float | None = None) -> FakeResponse:
            seen["timeout"] = timeout
            return FakeResponse()

        with (
            patch.dict("os.environ", ENVIRONMENT, clear=False),
            patch("urllib.request.urlopen", fake_urlopen),
            redirect_stdout(io.StringIO()),
        ):
            run_script()

        self.assertGreater(seen["timeout"], 60)


if __name__ == "__main__":
    unittest.main()
