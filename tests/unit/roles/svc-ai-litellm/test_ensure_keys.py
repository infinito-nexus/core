from __future__ import annotations

import importlib.util
import io
import json
import unittest
import urllib.error
from contextlib import redirect_stdout
from typing import ClassVar
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/svc-ai-litellm/files/ensure_keys.py"


def load_script() -> object:
    spec = importlib.util.spec_from_file_location("ensure_keys", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_script()


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("/", code, "", None, None)


class RecordingProxy:
    """A `call` answering from a declared key state, recording what it was asked."""

    def __init__(self, known_keys: set[str], held_aliases: set[str]) -> None:
        self.known_keys = known_keys
        self.held_aliases = held_aliases
        self.paths: list[str] = []

    def __call__(self, method: str, path: str, body: dict | None = None):
        self.paths.append(path)
        if path.startswith("/key/info"):
            if path.split("=", 1)[1] not in self.known_keys:
                raise http_error(404)
            return
        if path == "/key/delete":
            if not set(body["key_aliases"]) & self.held_aliases:
                raise http_error(404)
            self.held_aliases -= set(body["key_aliases"])
            return
        if body["key_alias"] in self.held_aliases:
            raise http_error(400)
        self.held_aliases.add(body["key_alias"])
        return


class TestEnsureKey(unittest.TestCase):
    ENTRY: ClassVar[dict[str, str]] = {"alias": "web-app-flowise", "key": "sk-new"}
    REPLACED: ClassVar[list[str]] = [
        "/key/info?key=sk-new",
        "/key/delete",
        "/key/generate",
    ]

    def test_registered_key_is_left_alone(self):
        proxy = RecordingProxy({"sk-new"}, {"web-app-flowise"})
        self.assertFalse(MODULE.ensure_key(self.ENTRY, proxy))
        self.assertEqual(proxy.paths, ["/key/info?key=sk-new"])

    def test_held_alias_is_released_before_the_key_is_created(self):
        proxy = RecordingProxy(set(), {"web-app-flowise"})
        self.assertTrue(MODULE.ensure_key(self.ENTRY, proxy))
        self.assertEqual(proxy.paths, self.REPLACED)

    def test_free_alias_survives_the_delete_that_finds_nothing(self):
        proxy = RecordingProxy(set(), set())
        self.assertTrue(MODULE.ensure_key(self.ENTRY, proxy))
        self.assertEqual(proxy.paths, self.REPLACED)

    def test_a_failing_creation_is_not_swallowed(self):
        def call(method, path, body=None):
            raise http_error(500 if path == "/key/generate" else 404)

        with self.assertRaises(urllib.error.HTTPError) as raised:
            MODULE.ensure_key(self.ENTRY, call)
        self.assertEqual(raised.exception.code, 500)


class TestHttpCall(unittest.TestCase):
    def _capture(self, method: str, path: str, body: dict | None):
        captured: dict = {}

        def urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["data"] = request.data
            captured["timeout"] = timeout

        call = MODULE.http_call("http://localhost:4000", {"X-Test": "1"})
        with patch.object(MODULE.urllib.request, "urlopen", urlopen):
            call(method, path, body)
        return captured

    def test_a_body_is_sent_as_json_on_the_declared_method(self):
        captured = self._capture("POST", "/key/delete", {"key_aliases": ["a"]})
        self.assertEqual(captured["url"], "http://localhost:4000/key/delete")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(json.loads(captured["data"]), {"key_aliases": ["a"]})
        self.assertEqual(captured["timeout"], MODULE.TIMEOUT)

    def test_a_bodyless_request_carries_no_payload(self):
        captured = self._capture("GET", "/key/info?key=x", None)
        self.assertEqual(captured["method"], "GET")
        self.assertIsNone(captured["data"])


class TestMain(unittest.TestCase):
    ENV: ClassVar[dict[str, str]] = {
        "LITELLM_PORT": "4000",
        "LITELLM_MK": "sk-master",
        "LITELLM_KEYS_PAYLOAD": json.dumps(
            [
                {"alias": "web-app-flowise", "key": "sk-new"},
                {"alias": "web-app-hermes", "key": "sk-known"},
            ]
        ),
    }

    def test_only_the_created_key_is_announced_as_changed(self):
        proxy = RecordingProxy({"sk-known"}, {"web-app-flowise"})
        buffer = io.StringIO()
        with (
            patch.dict("os.environ", self.ENV, clear=True),
            patch.object(MODULE, "http_call", return_value=proxy),
            redirect_stdout(buffer),
        ):
            MODULE.main()
        self.assertEqual(buffer.getvalue(), "CHANGED web-app-flowise\n")

    def test_the_master_key_reaches_the_proxy_as_a_bearer_header(self):
        with (
            patch.dict("os.environ", self.ENV, clear=True),
            patch.object(MODULE, "http_call") as http_call,
        ):
            http_call.return_value = RecordingProxy({"sk-new", "sk-known"}, set())
            MODULE.main()
        base, headers = http_call.call_args[0]
        self.assertEqual(base, "http://localhost:4000")
        self.assertEqual(headers["Authorization"], "Bearer sk-master")


if __name__ == "__main__":
    unittest.main()
