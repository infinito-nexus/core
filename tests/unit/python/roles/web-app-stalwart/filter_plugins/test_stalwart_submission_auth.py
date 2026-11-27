from __future__ import annotations

import importlib.util
import json
import unittest

from ansible.errors import AnsibleFilterError
from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-stalwart"
VARS = ROLE / ROLE_FILE_VARS_MAIN
LISTENER_CREATE = ROLE / "templates" / "jmap" / "listener" / "create.json.j2"
AUTH_UPDATE = ROLE / "templates" / "jmap" / "auth" / "update.json.j2"
SUBMISSION_PORT = 587
LIVE = {
    "saslMechanisms": {
        "match": {
            "0": {
                "if": "local_port != 25 && is_tls",
                "then": "[plain, login, oauthbearer, xoauth2]",
            }
        },
        "else": "false",
    },
    "require": {
        "match": {"0": {"if": "local_port != 25", "then": "true"}},
        "else": "false",
    },
}


def _load():
    path = ROLE / "filter_plugins" / "stalwart_submission_auth.py"
    spec = importlib.util.spec_from_file_location("stalwart_submission_auth", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _env() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["to_json"] = json.dumps
    return env


def _first(expression: dict) -> dict:
    return expression["match"]["0"]


class TestStalwartSubmissionAuth(unittest.TestCase):
    def setUp(self):
        self.auth = _load().stalwart_submission_auth

    def test_the_submission_port_offers_plain_without_tls(self):
        update = self.auth(LIVE, SUBMISSION_PORT)
        self.assertEqual(
            _first(update["saslMechanisms"]),
            {"if": f"local_port == {SUBMISSION_PORT}", "then": "[plain]"},
        )
        self.assertNotIn("is_tls", _first(update["saslMechanisms"])["if"])

    def test_the_submission_port_refuses_a_session_without_auth(self):
        update = self.auth(LIVE, SUBMISSION_PORT)
        self.assertEqual(
            _first(update["require"]),
            {"if": f"local_port == {SUBMISSION_PORT}", "then": "true"},
        )

    def test_the_live_terms_follow_in_their_order(self):
        update = self.auth(LIVE, SUBMISSION_PORT)
        for field, expression in LIVE.items():
            with self.subTest(field=field):
                self.assertEqual(update[field]["match"]["1"], expression["match"]["0"])
                self.assertEqual(update[field]["else"], expression["else"])
                self.assertEqual(len(update[field]["match"]), 2)

    def test_an_applied_update_changes_nothing_on_the_next_deploy(self):
        applied = {**LIVE, **self.auth(LIVE, SUBMISSION_PORT)}
        self.assertEqual(self.auth(applied, SUBMISSION_PORT), {})

    def test_a_stale_term_for_the_port_is_replaced(self):
        stale = {
            field: {
                "match": {
                    "0": {"if": f"local_port == {SUBMISSION_PORT}", "then": "false"},
                    "1": expression["match"]["0"],
                },
                "else": expression["else"],
            }
            for field, expression in LIVE.items()
        }
        update = self.auth(stale, SUBMISSION_PORT)
        for field in LIVE:
            with self.subTest(field=field):
                self.assertEqual(len(update[field]["match"]), 2)
                self.assertNotEqual(_first(update[field])["then"], "false")

    def test_a_constant_expression_gets_the_term_too(self):
        update = self.auth({"saslMechanisms": "false", "require": "false"}, "587")
        self.assertEqual(update["require"]["else"], "false")
        self.assertEqual(_first(update["require"])["then"], "true")

    def test_malformed_input_is_refused(self):
        for auth, port in (
            ([], SUBMISSION_PORT),
            ({"saslMechanisms": "false"}, SUBMISSION_PORT),
            ({"saslMechanisms": {"match": {}}, "require": "false"}, SUBMISSION_PORT),
            (LIVE, "smtp"),
        ):
            with (
                self.subTest(auth=auth, port=port),
                self.assertRaises(AnsibleFilterError),
            ):
                self.auth(auth, port)

    def test_the_update_payload_carries_the_filter_result(self):
        update = self.auth(LIVE, SUBMISSION_PORT)
        body = json.loads(
            _env()
            .from_string(read_text(AUTH_UPDATE))
            .render(stalwart_submission_auth=update)
        )
        method, arguments, _ = body["methodCalls"][0]
        self.assertEqual(method, "x:MtaStageAuth/set")
        self.assertEqual(arguments["update"]["singleton"], update)


class TestSubmissionListener(unittest.TestCase):
    def setUp(self):
        self.vars = load_yaml_any(str(VARS))

    def test_the_listener_binds_the_port_in_plaintext_smtp(self):
        listener = dict(self.vars["STALWART_SUBMISSION_LISTENER"])
        listener["bind"] = {
            _env()
            .from_string(bind)
            .render(STALWART_SUBMISSION_PORT=SUBMISSION_PORT): enabled
            for bind, enabled in listener["bind"].items()
        }
        body = json.loads(
            _env()
            .from_string(read_text(LISTENER_CREATE))
            .render(STALWART_SUBMISSION_LISTENER=listener)
        )
        method, arguments, _ = body["methodCalls"][0]
        created = arguments["create"]["submission"]
        self.assertEqual(method, "x:NetworkListener/set")
        self.assertEqual(set(created), {"name", "protocol", "bind"})
        self.assertEqual(created["bind"], {f"[::]:{SUBMISSION_PORT}": True})
        self.assertEqual(created["protocol"], "smtp")

    def test_only_authenticated_sessions_relay(self):
        relay = self.vars["STALWART_RELAY_RULE"]
        self.assertEqual(relay, "!is_empty(authenticated_as)")


if __name__ == "__main__":
    unittest.main()
