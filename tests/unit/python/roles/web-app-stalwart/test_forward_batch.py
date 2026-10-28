from __future__ import annotations

import json
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader
from ansible.template import Templar

from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-stalwart"
TASKS = ROLE / "tasks"
OWN = "infinito-forward"
SETUP = "16_forwards.yml"
APPLY = "16_forwards/apply.yml"
UPLOAD = "📤 Upload the changed forward scripts"
POINT = "📁 Point the forward scripts at their uploads and activate them"

filter_loader.add_directory(str(ROLE / "filter_plugins"))

ACCOUNT_IDS = {
    "kept@infinito.test": "k",
    "paused@infinito.test": "p",
    "fresh@infinito.test": "f",
    "moved@infinito.test": "m",
}
CHUNK = [
    {"address": "kept@infinito.test", "destinations": ["a@example.org"]},
    {"address": "paused@infinito.test", "destinations": ["b@example.org"]},
    {"address": "fresh@infinito.test", "destinations": ["c@example.org"]},
    {"address": "moved@infinito.test", "destinations": ["new@example.org"]},
]


def _flatten(tasks: list[dict]) -> list[dict]:
    flat = []
    for task in tasks:
        flat.append(task)
        flat.extend(_flatten(task.get("block") or []))
    return flat


def _task(path: str, name: str) -> dict:
    tasks = _flatten(load_yaml_any(str(TASKS / path), default_if_missing=[]))
    return next(t for t in tasks if t.get("name") == name)


def _render(template, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _with_task_vars(task: dict, variables: dict) -> dict:
    variables = dict(variables)
    for name, raw in (task.get("vars") or {}).items():
        if name != "stalwart_jmap_body":
            variables[name] = _render(raw, **variables)
    return variables


def _fact(path: str, name: str, fact: str, **variables):
    task = _task(path, name)
    return _render(
        task["ansible.builtin.set_fact"][fact], **_with_task_vars(task, variables)
    )


def _body(path: str, name: str, **variables) -> dict:
    task = _task(path, name)
    return json.loads(
        _render(
            task["vars"]["stalwart_jmap_body"], **_with_task_vars(task, variables)
        )
    )


def _when(path: str, name: str, **variables) -> bool:
    task = _task(path, name)
    return _render("{{ (" + task["when"] + ") | bool }}", **variables)


def _script(destinations: list[str], include: str = "") -> str:
    return _render(
        "{{ destinations | stalwart_forward_script(include) }}",
        destinations=destinations,
        include=include,
    )


def _upload(account: str, n: int, script: str) -> dict:
    return {
        "accountId": account,
        "create": {f"b{n}": {"data": [{"data:asText": script}]}},
    }


BASE = {
    "STALWART_FORWARD_SCRIPT_NAME": OWN,
    "STALWART_FORWARDS": CHUNK,
    "STALWART_JMAP_MAX_METHOD_CALLS": 16,
    "stalwart_forward_chunk": CHUNK,
    "stalwart_forward_account_ids": ACCOUNT_IDS,
}

LISTED = {
    "kept@infinito.test": [
        {"id": "s1", "name": OWN, "blobId": "B1", "isActive": True},
    ],
    "paused@infinito.test": [
        {"id": "s2", "name": OWN, "blobId": "B2", "isActive": False},
    ],
    "fresh@infinito.test": [
        {"id": "u3", "name": "rules", "blobId": "B3", "isActive": True},
    ],
    "moved@infinito.test": [
        {"id": "s4", "name": OWN, "blobId": "B4", "isActive": True},
    ],
}
TEXTS = {
    "kept@infinito.test": _script(["a@example.org"]),
    "paused@infinito.test": _script(["b@example.org"]),
    "moved@infinito.test": _script(["old@example.org"]),
}


def _states() -> list[dict]:
    return _fact(
        APPLY,
        "🔍 Find the forward script of every forwarding account",
        "stalwart_forward_states",
        **BASE,
        stalwart_jmap={
            "methodResponses": [
                ["SieveScript/get", {"list": scripts}, address]
                for address, scripts in reversed(list(LISTED.items()))
            ]
        },
    )


def _plan(texts: dict = TEXTS) -> list[dict]:
    return _fact(
        APPLY,
        "🔍 Render the forward script of every forwarding account",
        "stalwart_forward_plan",
        **BASE,
        stalwart_forward_states=_states(),
        stalwart_jmap={
            "methodResponses": [
                ["Blob/get", {"list": [{"id": "x", "data:asText": text}]}, address]
                for address, text in texts.items()
            ]
        },
    )


def _only(address: str) -> list[dict]:
    return [step for step in _plan() if step["address"] == address]


class TestForwardSetup(unittest.TestCase):
    def test_one_read_carries_the_limits_domains_and_accounts(self):
        body = _body(
            SETUP,
            "📖 Read the Sieve limits of user scripts and the accounts the forwards belong to",
            **BASE,
        )
        self.assertEqual(
            [call[0] for call in body["methodCalls"]],
            ["x:SieveUserInterpreter/get", "x:Domain/get", "x:Account/get"],
        )

    def test_accounts_resolve_by_their_full_address(self):
        ids = _fact(
            SETUP,
            "🔍 Check Sieve limits against the widest forward, resolve forwarders",
            "stalwart_forward_account_ids",
            **BASE,
            stalwart_jmap={
                "methodResponses": [
                    ["x:SieveUserInterpreter/get", {"list": [{}]}, "c0"],
                    [
                        "x:Domain/get",
                        {"list": [{"id": "d1", "name": "infinito.test"}]},
                        "c1",
                    ],
                    [
                        "x:Account/get",
                        {
                            "list": [
                                {"id": "k", "name": "Kept", "domainId": "d1"},
                                {"id": "z", "name": "kept", "domainId": "d9"},
                            ]
                        },
                        "c2",
                    ],
                ]
            },
        )
        self.assertEqual(ids, {"kept@infinito.test": "k"})

    def test_forwards_are_chunked_by_the_method_call_limit(self):
        loop = _task(
            SETUP, "📨 Keep the forward script of every forwarding account in place"
        )["loop"]
        forwards = [{"address": f"f{i}@infinito.test"} for i in range(17)]
        chunks = _render(
            loop, STALWART_FORWARDS=forwards, STALWART_JMAP_MAX_METHOD_CALLS=16
        )
        self.assertEqual([len(c) for c in chunks], [16, 1])


class TestForwardPhases(unittest.TestCase):
    def test_one_list_addresses_every_account_by_its_id(self):
        body = _body(
            APPLY, "📖 List the Sieve scripts of the forwarding accounts", **BASE
        )
        self.assertEqual(
            body["using"], ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:sieve"]
        )
        self.assertEqual(
            body["methodCalls"],
            [
                [
                    "SieveScript/get",
                    {"accountId": ACCOUNT_IDS[f["address"]], "ids": None},
                    f["address"],
                ]
                for f in CHUNK
            ],
        )

    def test_one_read_fetches_only_the_scripts_the_role_owns(self):
        body = _body(
            APPLY,
            "📖 Read the forward scripts the accounts already hold",
            **BASE,
            stalwart_forward_states=_states(),
        )
        self.assertEqual(
            body["methodCalls"],
            [
                [
                    "Blob/get",
                    {"accountId": account, "ids": [blob], "properties": ["data:asText"]},
                    address,
                ]
                for address, account, blob in (
                    ("kept@infinito.test", "k", "B1"),
                    ("paused@infinito.test", "p", "B2"),
                    ("moved@infinito.test", "m", "B4"),
                )
            ],
        )

    def test_the_plan_writes_changed_scripts_and_reactivates_paused_ones(self):
        plan = {step["address"]: step for step in _plan()}
        self.assertEqual(
            {a: (s["write"], s["activate"]) for a, s in plan.items()},
            {
                "kept@infinito.test": (False, False),
                "paused@infinito.test": (False, True),
                "fresh@infinito.test": (True, False),
                "moved@infinito.test": (True, False),
            },
        )
        self.assertEqual(
            plan["fresh@infinito.test"]["script"], _script(["c@example.org"], "rules")
        )
        self.assertEqual(plan["moved@infinito.test"]["own"], "s4")
        self.assertEqual(plan["fresh@infinito.test"]["own"], "")

    def test_an_owned_script_stalwart_did_not_return_is_named(self):
        texts = {a: t for a, t in TEXTS.items() if a != "paused@infinito.test"}
        unread = _render(
            _task(
                APPLY,
                "✅ Ensure Stalwart returned the forward script of every account that holds one",
            )["vars"]["stalwart_forward_unread"],
            stalwart_forward_plan=_plan(texts),
        )
        self.assertEqual(unread, ["paused@infinito.test"])

    def test_upload_and_set_touch_only_the_accounts_that_need_it(self):
        plan = _plan()
        upload = _body(APPLY, UPLOAD, **BASE, stalwart_forward_plan=plan)
        self.assertEqual(
            upload["methodCalls"],
            [
                [
                    "Blob/upload",
                    _upload("f", 2, _script(["c@example.org"], "rules")),
                    "fresh@infinito.test",
                ],
                [
                    "Blob/upload",
                    _upload("m", 3, _script(["new@example.org"])),
                    "moved@infinito.test",
                ],
            ],
        )
        point = _body(
            APPLY,
            POINT,
            **BASE,
            stalwart_forward_plan=plan,
            stalwart_jmap={
                "methodResponses": [
                    [
                        "Blob/upload",
                        {"created": {"b2": {"id": "N2"}}},
                        "fresh@infinito.test",
                    ],
                    [
                        "Blob/upload",
                        {"created": {"b3": {"id": "N3"}}},
                        "moved@infinito.test",
                    ],
                ]
            },
        )
        self.assertEqual(
            point["methodCalls"],
            [
                [
                    "SieveScript/set",
                    {"accountId": "p", "onSuccessActivateScript": "s2"},
                    "paused@infinito.test",
                ],
                [
                    "SieveScript/set",
                    {
                        "accountId": "f",
                        "create": {"f2": {"name": OWN, "blobId": "N2"}},
                        "onSuccessActivateScript": "#f2",
                    },
                    "fresh@infinito.test",
                ],
                [
                    "SieveScript/set",
                    {
                        "accountId": "m",
                        "update": {"s4": {"blobId": "N3"}},
                        "onSuccessActivateScript": "s4",
                    },
                    "moved@infinito.test",
                ],
            ],
        )

    def test_a_steady_state_skips_upload_and_set(self):
        plan = _only("kept@infinito.test")
        self.assertFalse(_when(APPLY, UPLOAD, stalwart_forward_plan=plan))
        self.assertFalse(_when(APPLY, POINT, stalwart_forward_plan=plan))

    def test_a_reactivation_alone_skips_the_upload_but_not_the_set(self):
        plan = _only("paused@infinito.test")
        self.assertFalse(_when(APPLY, UPLOAD, stalwart_forward_plan=plan))
        self.assertTrue(_when(APPLY, POINT, stalwart_forward_plan=plan))


if __name__ == "__main__":
    unittest.main()
