from __future__ import annotations

import hashlib
import json
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles" / "web-app-stalwart" / "tasks"
DESCRIPTION = "Infinito.Nexus submission"
RETIRED = "Infinito.Nexus submission, retired"
USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]

USERS = {
    "administrator": {
        "username": "administrator",
        "password": "admin-pw",
        "email": "administrator@infinito.test",
        "roles": [],
    },
    "no-reply": {
        "username": "no-reply",
        "password": "no-reply-pw",
        "email": "no-reply@infinito.test",
        "roles": ["bot"],
        "tokens": {"web-app-stalwart": "stored-app-password"},
    },
    "contact": {"username": "contact", "password": "contact-pw", "roles": ["bot"]},
}


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


def _fact(path: str, name: str, fact: str, **variables):
    return _render(_task(path, name)["ansible.builtin.set_fact"][fact], **variables)


def _body(path: str, name: str, **variables) -> dict:
    task = _task(path, name)
    variables = {**variables, **(task.get("vars") or {})}
    return json.loads(_render(task["vars"]["stalwart_jmap_body"], **variables))


def _assert_var(path: str, name: str, var: str, **variables):
    return _render(_task(path, name)["vars"][var], **variables)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


BASE = {
    "STALWART_USERS": USERS,
    "STALWART_DOMAIN": "infinito.test",
    "STALWART_JMAP_MAX_METHOD_CALLS": 16,
    "STALWART_BOT_APP_PASSWORD_DESCRIPTION": DESCRIPTION,
    "STALWART_BOT_APP_PASSWORD_RETIRED_DESCRIPTION": RETIRED,
    "application_id": "web-app-stalwart",
    "stalwart_domain_id": "d1",
    "stalwart_app_password_stale": {},
}

CREATE_RESPONSE = [
    [
        "x:Account/set",
        {
            "created": {"u0": {"id": "a"}},
            "notCreated": {
                "u1": {"type": "alreadyExists", "objectId": {"id": "b"}},
                "u2": {"type": "alreadyExists", "objectId": {"id": "c"}},
            },
        },
        "c0",
    ]
]


def _resolved() -> list[dict]:
    return _fact(
        "04_manage_user.yml",
        "🔍 Resolve the Stalwart accounts and their effective secrets",
        "stalwart_accounts",
        **BASE,
    )


def _matched(response: list = CREATE_RESPONSE, listed: tuple = ()) -> list[dict]:
    return _fact(
        "04_manage_user.yml",
        "🔍 Match every account to its Stalwart id",
        "stalwart_accounts",
        **BASE,
        stalwart_accounts=_resolved(),
        stalwart_jmap={
            "methodResponses": [
                *response,
                ["x:Account/get", {"list": list(listed)}, "c1"],
            ]
        },
    )


def _refused(accounts: list[dict], sso: bool = False) -> dict:
    return _assert_var(
        "04_manage_user.yml",
        "✅ Ensure Stalwart created or already holds every account",
        "stalwart_account_refused",
        STALWART_SSO_ENABLED=sso,
        stalwart_accounts=accounts,
    )


EXTERNAL = {
    "type": "forbidden",
    "description": "Cannot set credentials for accounts in an external directory.",
}
SSO_RESPONSE = [
    [
        "x:Account/set",
        {"notCreated": {"u0": EXTERNAL, "u1": EXTERNAL, "u2": EXTERNAL}},
        "c0",
    ]
]


class TestAccountPhases(unittest.TestCase):
    def test_bots_get_the_derived_secret_and_people_their_password(self):
        accounts = {a["key"]: a for a in _resolved()}
        self.assertEqual(accounts["administrator"]["secret"], "admin-pw")
        self.assertEqual(accounts["no-reply"]["secret"], _sha("no-reply-pw"))
        self.assertEqual(accounts["contact"]["address"], "contact@infinito.test")
        self.assertEqual(accounts["contact"]["description"], "contact")
        self.assertEqual(accounts["no-reply"]["stored"], "stored-app-password")
        self.assertEqual(accounts["contact"]["stored"], "")

    def test_one_create_carries_every_account(self):
        body = _body(
            "04_manage_user.yml",
            "📁 Create the Stalwart accounts",
            **BASE,
            stalwart_accounts=_resolved(),
        )
        self.assertEqual(body["using"], USING)
        self.assertEqual(len(body["methodCalls"]), 2)
        self.assertEqual(body["methodCalls"][1], ["x:Account/get", {"ids": None}, "c1"])
        method, arguments, _ = body["methodCalls"][0]
        self.assertEqual(method, "x:Account/set")
        creates = arguments["create"]
        self.assertEqual(sorted(creates), ["u0", "u1", "u2"])
        self.assertEqual(
            creates["u1"],
            {
                "@type": "User",
                "name": "no-reply",
                "domainId": "d1",
                "description": "no-reply@infinito.test",
                "credentials": {
                    "0": {"@type": "Password", "secret": _sha("no-reply-pw")}
                },
            },
        )

    def test_created_and_existing_accounts_get_their_ids(self):
        accounts = {a["key"]: a for a in _matched()}
        self.assertEqual(
            (accounts["administrator"]["id"], accounts["administrator"]["existing"]),
            ("a", False),
        )
        self.assertEqual(
            (accounts["no-reply"]["id"], accounts["no-reply"]["existing"]), ("b", True)
        )

    def test_a_refused_create_fails_naming_the_account(self):
        refusal = {"type": "invalidProperties", "properties": ["name"]}
        response = [
            [
                "x:Account/set",
                {
                    "created": {"u0": {"id": "a"}, "u1": {"id": "b"}},
                    "notCreated": {"u2": refusal},
                },
                "c0",
            ]
        ]
        refused = _refused(_matched(response))
        self.assertEqual(refused, {"contact@infinito.test": refusal})

    def test_an_existing_account_without_an_id_fails(self):
        response = [
            ["x:Account/set", {"notCreated": {"u0": {"type": "alreadyExists"}}}, "c0"]
        ]
        refused = _refused(_matched(response))
        self.assertIn("administrator@infinito.test", refused)

    def test_accounts_of_an_external_directory_take_their_listed_ids(self):
        listed = (
            {"id": "a", "name": "administrator", "domainId": "d1"},
            {"id": "b", "name": "No-Reply", "domainId": "d1"},
            {"id": "c", "name": "contact", "domainId": "d1"},
        )
        accounts = {a["key"]: a for a in _matched(SSO_RESPONSE, listed)}
        self.assertEqual(
            {key: (a["id"], a["existing"]) for key, a in accounts.items()},
            {
                "administrator": ("a", False),
                "no-reply": ("b", False),
                "contact": ("c", False),
            },
        )
        self.assertEqual(_refused(list(accounts.values()), sso=True), {})

    def test_an_account_of_another_domain_is_not_taken(self):
        listed = ({"id": "x", "name": "administrator", "domainId": "d2"},)
        accounts = {a["key"]: a for a in _matched(SSO_RESPONSE, listed)}
        self.assertEqual(accounts["administrator"]["id"], "")

    def test_a_person_unknown_to_an_external_directory_is_tolerated_under_sso(self):
        listed = (
            {"id": "b", "name": "no-reply", "domainId": "d1"},
            {"id": "c", "name": "contact", "domainId": "d1"},
        )
        self.assertEqual(_refused(_matched(SSO_RESPONSE, listed), sso=True), {})

    def test_a_bot_without_an_account_fails_under_sso(self):
        listed = (
            {"id": "a", "name": "administrator", "domainId": "d1"},
            {"id": "c", "name": "contact", "domainId": "d1"},
        )
        refused = _refused(_matched(SSO_RESPONSE, listed), sso=True)
        self.assertEqual(refused, {"no-reply@infinito.test": EXTERNAL})

    def test_a_forbidden_create_fails_without_sso(self):
        refused = _refused(_matched(SSO_RESPONSE))
        self.assertEqual(
            sorted(refused),
            [
                "administrator@infinito.test",
                "contact@infinito.test",
                "no-reply@infinito.test",
            ],
        )

    def test_one_update_carries_every_existing_account(self):
        body = _body(
            "04_manage_user.yml",
            "🔄 Send the passwords of the pre-existing accounts",
            **BASE,
            stalwart_accounts=_matched(),
        )
        method, arguments, _ = body["methodCalls"][0]
        self.assertEqual(method, "x:Account/set")
        self.assertEqual(sorted(arguments["update"]), ["b", "c"])
        self.assertEqual(
            arguments["update"]["c"]["credentials"]["0"]["secret"], _sha("contact-pw")
        )

    def test_a_refused_update_fails_naming_the_account(self):
        refused = _assert_var(
            "04_manage_user.yml",
            "✅ Ensure Stalwart took the password of every pre-existing account",
            "stalwart_account_refused",
            stalwart_accounts=_matched(),
            stalwart_jmap={
                "methodResponses": [
                    [
                        "x:Account/set",
                        {"updated": {"b": None}, "notUpdated": {"c": {"type": "x"}}},
                        "c0",
                    ]
                ]
            },
        )
        self.assertEqual(refused, {"contact@infinito.test": {"type": "x"}})

    def test_bots_are_chunked_by_the_method_call_limit(self):
        loop = _task(
            "04_manage_user.yml", "🔑 Keep an app password for every bot under SSO"
        )["loop"]
        bots = [{"bot": True, "address": f"b{i}"} for i in range(17)]
        chunks = _render(
            loop,
            stalwart_accounts=[*bots, {"bot": False}],
            STALWART_JMAP_MAX_METHOD_CALLS=16,
        )
        self.assertEqual([len(c) for c in chunks], [16, 1])


def _bots() -> list[dict]:
    return [a for a in _matched() if a["bot"]]


def _plan(listed: dict) -> list[dict]:
    return _fact(
        "04_manage_user/app_password.yml",
        "🔍 Decide which bots need a new app password",
        "stalwart_app_password_plan",
        **BASE,
        stalwart_bots=_bots(),
        stalwart_jmap={
            "methodResponses": [
                ["x:AppPassword/get", {"list": entries}, address]
                for address, entries in listed.items()
            ]
        },
    )


LISTED = {
    "no-reply@infinito.test": [
        {"id": "1", "description": DESCRIPTION},
        {"id": "2", "description": RETIRED},
    ],
    "contact@infinito.test": [
        {"id": "1", "description": DESCRIPTION},
        {"id": "4", "description": DESCRIPTION},
        {"id": "5", "description": "Laptop"},
    ],
}


class TestAppPasswordPhases(unittest.TestCase):
    def test_one_list_addresses_every_bot_by_account_id(self):
        body = _body(
            "04_manage_user/app_password.yml",
            "📖 List the app passwords of the bots",
            **BASE,
            stalwart_bots=_bots(),
        )
        self.assertEqual(
            body["methodCalls"],
            [
                [
                    "x:AppPassword/get",
                    {"accountId": "b", "ids": None},
                    "no-reply@infinito.test",
                ],
                [
                    "x:AppPassword/get",
                    {"accountId": "c", "ids": None},
                    "contact@infinito.test",
                ],
            ],
        )

    def test_the_plan_reads_each_bot_from_its_own_call(self):
        plan = {p["key"]: p for p in _plan(dict(reversed(list(LISTED.items()))))}
        self.assertFalse(plan["no-reply"]["renew"])
        self.assertEqual(plan["no-reply"]["drop"], ["2"])
        self.assertTrue(plan["contact"]["renew"])
        self.assertEqual(plan["contact"]["owned"], ["1", "4"])
        self.assertEqual(plan["contact"]["drop"], ["1", "4"])

    def test_a_stored_derived_secret_renews(self):
        bots = _bots()
        bots[0]["stored"] = bots[0]["secret"]
        plan = _fact(
            "04_manage_user/app_password.yml",
            "🔍 Decide which bots need a new app password",
            "stalwart_app_password_plan",
            **BASE,
            stalwart_bots=bots,
            stalwart_jmap={
                "methodResponses": [
                    ["x:AppPassword/get", {"list": entries}, address]
                    for address, entries in LISTED.items()
                ]
            },
        )
        self.assertTrue(plan[0]["renew"])

    def test_mint_retire_and_drop_touch_only_the_renewed_bot(self):
        plan = _plan(LISTED)
        variables = {**BASE, "stalwart_app_password_plan": plan}
        mint = _body(
            "04_manage_user/app_password.yml",
            "🔑 Mint the new app passwords",
            **variables,
        )
        self.assertEqual(
            mint["methodCalls"],
            [
                [
                    "x:AppPassword/set",
                    {"accountId": "c", "create": {"p": {"description": DESCRIPTION}}},
                    "contact@infinito.test",
                ]
            ],
        )
        minted = _fact(
            "04_manage_user/app_password.yml",
            "🔍 Read the minted app passwords",
            "stalwart_app_password_minted",
            **variables,
            stalwart_jmap={
                "methodResponses": [
                    [
                        "x:AppPassword/set",
                        {"created": {"p": {"id": "6", "secret": "fresh"}}},
                        "contact@infinito.test",
                    ]
                ]
            },
        )
        self.assertEqual(
            minted,
            [{"key": "contact", "address": "contact@infinito.test", "secret": "fresh"}],
        )
        retire = _body(
            "04_manage_user/app_password.yml",
            "🏷️ Retire the app passwords the new ones replace",
            **variables,
        )
        self.assertEqual(
            retire["methodCalls"],
            [
                [
                    "x:AppPassword/set",
                    {
                        "accountId": "c",
                        "update": {
                            "1": {"description": RETIRED},
                            "4": {"description": RETIRED},
                        },
                    },
                    "contact@infinito.test",
                ]
            ],
        )
        stale = _fact(
            "04_manage_user/app_password.yml",
            "📥 Record the retired app passwords per bot",
            "stalwart_app_password_stale",
            **variables,
        )
        self.assertEqual(
            stale,
            {
                "no-reply@infinito.test": {"account": "b", "ids": ["2"]},
                "contact@infinito.test": {"account": "c", "ids": ["1", "4"]},
            },
        )
        drop_task = _task(
            "04_manage_user/app_password_drop.yml",
            "🗑️ Destroy the retired app passwords of the bots",
        )
        chunks = _render(
            drop_task["loop"],
            stalwart_app_password_stale=stale,
            STALWART_JMAP_MAX_METHOD_CALLS=16,
        )
        self.assertEqual(len(chunks), 1)
        drop = json.loads(
            _render(
                drop_task["vars"]["stalwart_jmap_body"],
                stalwart_app_password_owners=chunks[0],
            )
        )
        self.assertEqual(
            drop["methodCalls"],
            [
                [
                    "x:AppPassword/set",
                    {"accountId": "b", "destroy": ["2"]},
                    "no-reply@infinito.test",
                ],
                [
                    "x:AppPassword/set",
                    {"accountId": "c", "destroy": ["1", "4"]},
                    "contact@infinito.test",
                ],
            ],
        )

    def test_the_record_keeps_the_owners_of_an_earlier_chunk(self):
        stale = _fact(
            "04_manage_user/app_password.yml",
            "📥 Record the retired app passwords per bot",
            "stalwart_app_password_stale",
            **{
                **BASE,
                "stalwart_app_password_stale": {
                    "bounce@infinito.test": {"account": "z", "ids": ["9"]}
                },
            },
            stalwart_app_password_plan=_plan(LISTED),
        )
        self.assertEqual(
            sorted(stale),
            ["bounce@infinito.test", "contact@infinito.test", "no-reply@infinito.test"],
        )


if __name__ == "__main__":
    unittest.main()
