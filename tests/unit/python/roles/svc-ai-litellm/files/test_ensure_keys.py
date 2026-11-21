from __future__ import annotations

import importlib.util
import io
import json
import unittest
import urllib.error
from contextlib import redirect_stdout
from typing import ClassVar
from unittest.mock import patch

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/svc-ai-litellm/files/python/ensure_keys.py"


def load_script() -> object:
    spec = importlib.util.spec_from_file_location("ensure_keys", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_script()


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("/", code, "", None, None)


class RecordingProxy:
    def __init__(self, known_keys: set[str], held_aliases: set[str]) -> None:
        self.known_keys = known_keys
        self.held_aliases = held_aliases
        self.requests: list[tuple[str, str]] = []
        self.bodies: list[dict | None] = []

    @property
    def paths(self) -> list[str]:
        return [path for _method, path in self.requests]

    def __call__(self, method: str, path: str, body: dict | None = None):
        self.requests.append((method, path))
        self.bodies.append(body)
        if path.startswith("/key/list"):
            listed = [{"key_alias": alias} for alias in sorted(self.held_aliases)]
            return io.StringIO(json.dumps({"keys": listed, "total_pages": 1}))
        if path.startswith("/key/info"):
            raise http_error(404)
        if path == "/v2/key/info":
            if method != "POST":
                raise http_error(405)
            info = [
                {"key_alias": "x"} for key in body["keys"] if key in self.known_keys
            ]
            return io.StringIO(json.dumps({"key": body["keys"], "info": info}))
        if path == "/key/delete":
            if not set(body["key_aliases"]) & self.held_aliases:
                raise http_error(404)
            self.held_aliases -= set(body["key_aliases"])
            return None
        if body["key_alias"] in self.held_aliases:
            raise http_error(400)
        self.held_aliases.add(body["key_alias"])
        return None


class TestEnsureKey(unittest.TestCase):
    ENTRY: ClassVar[dict[str, str]] = {"alias": "web-app-flowise", "key": "sk-new"}
    REPLACED: ClassVar[list[str]] = [
        "/v2/key/info",
        "/key/delete",
        "/key/generate",
    ]

    def test_registered_key_is_left_alone(self):
        proxy = RecordingProxy({"sk-new"}, {"web-app-flowise"})
        self.assertFalse(MODULE.ensure_key(self.ENTRY, proxy))
        self.assertEqual(proxy.requests, [("POST", "/v2/key/info")])

    def test_the_key_travels_in_the_body_never_in_the_url(self):
        for known in ({"sk-new"}, set()):
            with self.subTest(known=known):
                proxy = RecordingProxy(known, {"web-app-flowise"})
                MODULE.ensure_key(self.ENTRY, proxy)
                self.assertEqual([path for path in proxy.paths if "sk-new" in path], [])
                self.assertEqual(proxy.requests[0], ("POST", "/v2/key/info"))
                self.assertEqual(proxy.bodies[0], {"keys": ["sk-new"]})

    def test_a_failing_lookup_releases_no_alias(self):
        calls: list[tuple[str, str]] = []

        def call(method, path, body=None):
            calls.append((method, path))
            raise http_error(500)

        with self.assertRaises(urllib.error.HTTPError):
            MODULE.ensure_key(self.ENTRY, call)
        self.assertEqual(calls, [("POST", "/v2/key/info")])

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
            if path == "/v2/key/info":
                return io.StringIO(json.dumps({"key": body["keys"], "info": []}))
            raise http_error(500 if path == "/key/generate" else 404)

        with self.assertRaises(urllib.error.HTTPError) as raised:
            MODULE.ensure_key(self.ENTRY, call)
        self.assertEqual(raised.exception.code, 500)


class TestRevokeStaleHostKeys(unittest.TestCase):
    def test_a_host_the_inventory_no_longer_names_loses_its_key(self):
        proxy = RecordingProxy(
            set(), {"web-app-flowise", "host:galaxyserver", "host:hotelserver"}
        )
        revoked = MODULE.revoke_stale_host_keys(
            ["web-app-flowise", "host:galaxyserver"], proxy
        )
        self.assertEqual(revoked, ["host:hotelserver"])
        self.assertEqual(proxy.held_aliases, {"web-app-flowise", "host:galaxyserver"})

    def test_a_local_consumer_is_never_revoked_here(self):
        proxy = RecordingProxy(set(), {"web-app-flowise", "web-app-hermes"})
        self.assertEqual(MODULE.revoke_stale_host_keys([], proxy), [])
        self.assertEqual(proxy.held_aliases, {"web-app-flowise", "web-app-hermes"})
        self.assertNotIn("/key/delete", proxy.paths)

    def test_every_page_of_the_key_list_is_read(self):
        pages = {
            1: {"keys": [{"key_alias": "host:galaxyserver"}], "total_pages": 2},
            2: {
                "keys": [{"key_alias": "host:hotelserver"}, "hashed"],
                "total_pages": 2,
            },
        }
        deleted: list[list[str]] = []

        def call(method, path, body=None):
            if path.startswith("/key/list"):
                page = int(path.rsplit("page=", 1)[1])
                return io.StringIO(json.dumps(pages[page]))
            deleted.append(body["key_aliases"])
            return None

        self.assertEqual(
            MODULE.revoke_stale_host_keys([], call),
            ["host:galaxyserver", "host:hotelserver"],
        )
        self.assertEqual(deleted, [["host:galaxyserver", "host:hotelserver"]])


def _conditions(task) -> list[str]:
    when = task.get("when") or []
    return [when] if isinstance(when, str) else list(when)


def _flatten(tasks, inherited=()):
    for task in tasks or []:
        conditions = (*inherited, *_conditions(task))
        yield task, conditions
        yield from _flatten(task.get("block"), conditions)


def _gated_on_consumers(conditions) -> bool:
    return any("LITELLM_CONSUMER_KEYS" in condition for condition in conditions)


def _revocation_runs_without_consumers(core_tasks, key_tasks) -> bool:
    include = next(
        conditions
        for task, conditions in _flatten(core_tasks)
        if task.get("ansible.builtin.include_tasks") == "01_keys.yml"
    )
    ensure = next(
        conditions
        for task, conditions in _flatten(key_tasks)
        if "ensure_keys.py" in str(task.get("ansible.builtin.shell", ""))
    )
    return not _gated_on_consumers(include) and not _gated_on_consumers(ensure)


class TestRevocationRunsWheneverTheGatewayRuns(unittest.TestCase):
    ROLE = PROJECT_ROOT / "roles/svc-ai-litellm/tasks"

    def test_a_gateway_without_local_consumers_still_revokes(self):
        self.assertTrue(
            _revocation_runs_without_consumers(
                load_yaml_any(self.ROLE / "00_core.yml"),
                load_yaml_any(self.ROLE / "01_keys.yml"),
            )
        )

    def test_the_check_refuses_the_key_step_gated_on_local_consumers(self):
        key_tasks = load_yaml_any(self.ROLE / "01_keys.yml")
        include = {"ansible.builtin.include_tasks": "01_keys.yml"}
        gated_task = [{**include, "when": "LITELLM_CONSUMER_KEYS | length > 0"}]
        gated_block = [
            {"when": ["LITELLM_CONSUMER_KEYS | length > 0"], "block": [include]}
        ]
        for core_tasks in (gated_task, gated_block):
            with self.subTest(core_tasks=core_tasks):
                self.assertFalse(
                    _revocation_runs_without_consumers(core_tasks, key_tasks)
                )

    def test_the_steps_that_need_a_consumer_key_stay_gated(self):
        conditions = next(
            conditions
            for task, conditions in _flatten(load_yaml_any(self.ROLE / "01_keys.yml"))
            if task.get("ansible.builtin.include_tasks") == "utils/prove_keys.yml"
        )
        self.assertTrue(_gated_on_consumers(conditions))


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
        captured = self._capture("GET", "/key/list?page=1", None)
        self.assertEqual(captured["method"], "GET")
        self.assertIsNone(captured["data"])


class TestMain(unittest.TestCase):
    ENV: ClassVar[dict[str, str]] = {
        "LITELLM_PORT": "4000",
        "LITELLM_MASTER_KEY": "sk-master",
    }
    PAYLOAD: ClassVar[list[dict[str, str]]] = [
        {"alias": "web-app-flowise", "key": "sk-new"},
        {"alias": "web-app-hermes", "key": "sk-known"},
    ]

    def test_only_the_created_key_is_announced_as_changed(self):
        proxy = RecordingProxy({"sk-known"}, {"web-app-flowise"})
        buffer = io.StringIO()
        with (
            patch.dict("os.environ", self.ENV, clear=True),
            patch.object(MODULE.sys, "stdin", io.StringIO(json.dumps(self.PAYLOAD))),
            patch.object(MODULE, "http_call", return_value=proxy),
            redirect_stdout(buffer),
        ):
            MODULE.main()
        self.assertEqual(buffer.getvalue(), "CHANGED web-app-flowise\n")

    def test_a_revoked_host_key_is_announced(self):
        proxy = RecordingProxy({"sk-new", "sk-known"}, {"host:hotelserver"})
        buffer = io.StringIO()
        with (
            patch.dict("os.environ", self.ENV, clear=True),
            patch.object(MODULE.sys, "stdin", io.StringIO(json.dumps(self.PAYLOAD))),
            patch.object(MODULE, "http_call", return_value=proxy),
            redirect_stdout(buffer),
        ):
            MODULE.main()
        self.assertEqual(buffer.getvalue(), "REVOKED host:hotelserver\n")
        self.assertNotIn("host:hotelserver", proxy.held_aliases)

    def test_without_local_consumers_a_removed_host_still_loses_its_key(self):
        proxy = RecordingProxy(set(), {"host:hotelserver"})
        buffer = io.StringIO()
        with (
            patch.dict("os.environ", self.ENV, clear=True),
            patch.object(MODULE.sys, "stdin", io.StringIO("[]")),
            patch.object(MODULE, "http_call", return_value=proxy),
            redirect_stdout(buffer),
        ):
            MODULE.main()
        self.assertEqual(buffer.getvalue(), "REVOKED host:hotelserver\n")
        self.assertEqual(proxy.held_aliases, set())

    def test_the_master_key_reaches_the_proxy_as_a_bearer_header(self):
        with (
            patch.dict("os.environ", self.ENV, clear=True),
            patch.object(MODULE.sys, "stdin", io.StringIO(json.dumps(self.PAYLOAD))),
            patch.object(MODULE, "http_call") as http_call,
        ):
            http_call.return_value = RecordingProxy({"sk-new", "sk-known"}, set())
            MODULE.main()
        base, headers = http_call.call_args[0]
        self.assertEqual(base, "http://localhost:4000")
        self.assertEqual(headers["Authorization"], "Bearer sk-master")


if __name__ == "__main__":
    unittest.main()
