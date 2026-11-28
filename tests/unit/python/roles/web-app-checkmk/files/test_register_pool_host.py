from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

from utils import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-checkmk"
    / "files"
    / "python"
    / "register_pool_host.py"
)
HOST = "infinito-infra"
FILE = "/etc/infinito/pool/pool.txt"
SITE = "cmk"
RULES = "/domain-types/rule/collections/all"


def _load():
    spec = spec_from_file_location("register_pool_host", SCRIPT)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pool = _load()
COMMAND = pool.program(FILE)


class FakeCheckmk:
    """
    Args:
        hosts: the host names the site holds.
        rules: the datasource program rules the site holds, as the API lists them.
        busy_polls: how many discovery polls answer that it still runs.
        status: overrides the answer of every call when set.
    """

    def __init__(self, hosts, rules, busy_polls, status):
        self.hosts = set(hosts)
        self.rules = list(rules)
        self.busy_polls = busy_polls
        self.status = status
        self.calls = []

    def __call__(self, method, path, payload=None, headers=None):
        self.calls.append((method, path, payload, headers))
        if self.status is not None:
            return self.status, {"detail": "refused"}
        if path == f"/objects/host_config/{HOST}":
            return (200, {"id": HOST}) if HOST in self.hosts else (404, {})
        if method == "POST" and path == "/domain-types/host_config/collections/all":
            self.hosts.add(payload["host_name"])
            return 200, {"id": payload["host_name"]}
        if method == "GET" and path.startswith(RULES):
            return 200, {"value": self.rules}
        if method == "POST" and path == RULES:
            self.rules.append(self._rule(f"r{len(self.rules)}", payload))
            return 200, {}
        if method == "PUT" and path.startswith("/objects/rule/"):
            rule_id = path.rsplit("/", 1)[1]
            self.rules = [
                self._rule(rule_id, payload) if rule["id"] == rule_id else rule
                for rule in self.rules
            ]
            return 200, {}
        if path.endswith("/activate-changes/invoke"):
            return 422, {"title": "no changes"}
        if path.endswith("/service_discovery_run/actions/start/invoke"):
            return 200, {}
        if path == f"/objects/service_discovery_run/{HOST}":
            active = self.busy_polls > 0
            self.busy_polls -= 1
            return 200, {"extensions": {"active": active}}
        raise AssertionError(f"unexpected call {method} {path}")

    @staticmethod
    def _rule(rule_id, payload):
        return {
            "id": rule_id,
            "extensions": {
                "properties": payload["properties"],
                "value_raw": payload["value_raw"],
                "conditions": payload["conditions"],
            },
        }

    def writes(self):
        return [
            (method, path)
            for method, path, _payload, _headers in self.calls
            if method in ("POST", "PUT")
            and "activate-changes" not in path
            and "service_discovery_run" not in path
        ]


def _register(site):
    sleeps = []
    changed = pool.register(site, HOST, COMMAND, SITE, sleeps.append)
    return changed, sleeps


class TestTheRegistration(unittest.TestCase):
    def test_a_fresh_site_gets_the_host_its_rule_and_a_discovery(self) -> None:
        site = FakeCheckmk((), (), 0, None)
        changed, _sleeps = _register(site)
        self.assertTrue(changed)
        self.assertIn(HOST, site.hosts)
        (rule,) = site.rules
        self.assertEqual(rule["extensions"]["value_raw"], repr(f"cat {FILE}"))
        self.assertEqual(
            rule["extensions"]["conditions"]["host_name"]["match_on"], [HOST]
        )
        starts = [call for call in site.calls if call[1].endswith("start/invoke")]
        self.assertEqual(starts[0][2], {"host_name": HOST, "mode": "fix_all"})
        activations = [
            c for c in site.calls if c[1].endswith("activate-changes/invoke")
        ]
        self.assertEqual(len(activations), 2)
        self.assertEqual(activations[0][3], {"If-Match": "*"})

    def test_negative_control_a_second_run_writes_nothing(self) -> None:
        site = FakeCheckmk((), (), 0, None)
        _register(site)
        site.calls.clear()
        changed, _sleeps = _register(site)
        self.assertFalse(changed)
        self.assertEqual(site.writes(), [])

    def test_a_rule_with_another_command_is_rewritten_in_place(self) -> None:
        stale = FakeCheckmk._rule(
            "r0",
            {
                "properties": {"description": pool.MARKER, "disabled": False},
                "value_raw": repr("cat /old/pool.txt"),
                "conditions": {"host_name": {"match_on": [HOST], "operator": "one_of"}},
            },
        )
        site = FakeCheckmk((HOST,), (stale,), 0, None)
        changed, _sleeps = _register(site)
        self.assertTrue(changed)
        self.assertEqual(site.writes(), [("PUT", "/objects/rule/r0")])
        self.assertEqual(site.rules[0]["extensions"]["value_raw"], repr(COMMAND))

    def test_a_foreign_rule_is_left_alone(self) -> None:
        foreign = FakeCheckmk._rule(
            "r0",
            {
                "properties": {"description": "someone else"},
                "value_raw": repr(COMMAND),
                "conditions": {},
            },
        )
        site = FakeCheckmk((HOST,), (foreign,), 0, None)
        _register(site)
        self.assertEqual(site.writes(), [("POST", RULES)])
        self.assertEqual(site.rules[0], foreign)


class TestTheDiscoveryWait(unittest.TestCase):
    def test_a_running_discovery_is_awaited(self) -> None:
        site = FakeCheckmk((HOST,), (), 2, None)
        _changed, sleeps = _register(site)
        self.assertEqual(sleeps, [pool.DISCOVERY_POLL_SECONDS] * 2)

    def test_a_discovery_that_never_ends_stays_pending(self) -> None:
        site = FakeCheckmk((HOST,), (), pool.DISCOVERY_POLLS + 1, None)
        with self.assertRaises(pool.CheckmkError) as raised:
            _register(site)
        self.assertIn(raised.exception.status, pool.TRANSIENT_STATUS)


class TestTheVerdict(unittest.TestCase):
    def _main(self, target, status):
        env = {
            "CHECKMK_API": "http://localhost:5000/cmk/check_mk/api/1.0",
            "CHECKMK_ADMIN_USER": "cmkadmin",
            "CHECKMK_ADMIN_PASSWORD": "unused",
            "CHECKMK_SITE": SITE,
            "POOL_HOST": HOST,
            "POOL_FILE": str(target),
        }
        site = FakeCheckmk((), (), 0, status)
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(pool, "call", lambda *args, **_kwargs: site(*args[3:])),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = pool.main()
        return code, out.getvalue(), err.getvalue()

    def test_an_unwritten_check_file_stays_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, _out, err = self._main(Path(tmp) / "pool.txt", None)
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("PENDING "))

    def test_a_refused_login_is_rejected_at_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "pool.txt"
            target.write_text("<<<local:sep(0)>>>\n", encoding="utf-8")
            code, _out, err = self._main(target, 401)
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("REJECTED "))

    def test_negative_control_a_sound_site_prints_its_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "pool.txt"
            target.write_text("<<<local:sep(0)>>>\n", encoding="utf-8")
            code, out, _err = self._main(target, None)
        self.assertEqual((code, out.strip()), (0, "CHANGED"))


if __name__ == "__main__":
    unittest.main()
