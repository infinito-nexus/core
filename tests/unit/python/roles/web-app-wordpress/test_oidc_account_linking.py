from __future__ import annotations

import base64
import json
import os
import re
import shlex
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils.cache import base as cache_base
from utils.cache.files import read_text
from utils.cache.reset import _reset_cache_for_tests
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/web-app-wordpress"
ADDON_TASKS_ENTRY = ROLE / "tasks/addons/daggerhart-openid-connect-generic.yml"
ADDON_TASKS = ROLE / "tasks/addons/daggerhart-openid-connect-generic-stack-host.yml"
REALM = PROJECT_ROOT / "roles/web-app-keycloak/templates/import/realm.json.j2"
OIDC_VARS = PROJECT_ROOT / "group_vars/all/11_oidc.yml"
EMAIL_CLAIM = re.compile(
    r'"user\.attribute":\s*"email",[^{}]*?"claim\.name":\s*"(?P<claim>[^"]+)"'
)
SUBJECT_META_KEY = "openid-connect-generic-subject-identity"
PREFIXED = "wp_" + SUBJECT_META_KEY
SITE_PREFIXED = "wp_2_" + SUBJECT_META_KEY
ADMIN = "platformadmin"
KEYCLOAK_ID = "6f1c0d3e-8b5a-4f0e-9d2c-1a7b3c5e9f00"
OTHER_ID = "0d9e8f7a-6b5c-4d3e-2f1a-0b9c8d7e6f5a"
KCADM_USERS = [
    {"id": "decoy-id", "username": ADMIN + "2"},
    {"id": KEYCLOAK_ID, "username": ADMIN},
]
MALLORY = {"ID": 7, "user_login": "mallory"}
DUPLICATE = {"ID": 9, "user_login": ADMIN + "2"}
OTHER_HOLDERS = [MALLORY, DUPLICATE]
WORDPRESS = {
    "WORDPRESS_USER": "www-data",
    "WORDPRESS_CONTAINER_ADDRESS": "wordpress",
    "WORDPRESS_ADMIN_USER": ADMIN,
    "WORDPRESS_DOCKER_HTML_PATH": "/var/www/html",
}
LOCAL_ORIGIN = "https://auth.example.test"
LOCAL_ISSUER = LOCAL_ORIGIN + "/realms/infinito"
EXTERNAL_ISSUER = "https://sso.example.org/realms/infinito"
TOKEN_PATH = "/protocol/openid-connect/token"

ADMIN_KEYS = "{{ WORDPRESS_ADMIN_USER | quote }} --fields=meta_key --format"
ADMIN_IDENTITY_KEYS = "wordpress_oidc_admin_identity_keys"
ADMIN_IDENTITY_READ = "--keys={{ " + ADMIN_IDENTITY_KEYS + " | join(',') | quote }}"
SUBJECT_FACT = "wordpress_oidc_admin_subject"
SETTINGS_WRITE = "wp eval-file"
STORE = "wp user meta update"
HOLDERS = "--fields=ID,user_login"
STRAY_KEYS = "{{ item.ID | quote }} --fields=meta_key --format"
STRAY_IDENTITIES = "item.item.ID"
UNBIND = "wp user meta delete"
OWNERS = "--fields=user_login --format"

filter_loader.add_directory(str(ROLE / "filter_plugins"))


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _tasks() -> list[dict]:
    return load_yaml_any(str(ADDON_TASKS), default_if_missing=[])


def _task_running(fragment: str) -> dict:
    matches = [
        t for t in _tasks() if fragment in str(t.get("ansible.builtin.shell", ""))
    ]
    assert len(matches) == 1, f"{ADDON_TASKS} must run '{fragment}' in exactly one task"
    return matches[0]


def _argv(task: dict, **variables) -> list[str]:
    return shlex.split(_render(task["ansible.builtin.shell"], **variables))


def _holds(condition: str, **variables) -> bool:
    return _render("{{ " + condition + " }}", **variables)


def _fact_setting(name: str) -> dict:
    matches = [
        t["ansible.builtin.set_fact"]
        for t in _tasks()
        if name in t.get("ansible.builtin.set_fact", {})
    ]
    assert len(matches) == 1, f"{ADDON_TASKS} must set {name} in one set_fact"
    return matches[0]


def _index(task: dict) -> int:
    return _tasks().index(task)


def _admin_subject() -> dict:
    lookup = _task_running("kcadm.sh get users")
    kcadm = {lookup["register"]: {"stdout": json.dumps(KCADM_USERS)}}
    expression = _fact_setting(SUBJECT_FACT)[SUBJECT_FACT]
    return {SUBJECT_FACT: _render(expression, WORDPRESS_ADMIN_USER=ADMIN, **kcadm)}


def _identity_keys(admin_keys: list[str]) -> list[str]:
    listing = _task_running(ADMIN_KEYS)
    listed = {
        listing["register"]: {
            "stdout": json.dumps([{"meta_key": k} for k in admin_keys])
        }
    }
    return _render(_fact_setting(ADMIN_IDENTITY_KEYS)[ADMIN_IDENTITY_KEYS], **listed)


def _identity_reads() -> tuple[dict, dict]:
    reads = [
        t
        for t in _tasks()
        if ADMIN_IDENTITY_READ in str(t.get("ansible.builtin.shell"))
    ]
    store = _index(_task_running(STORE))
    before = [t for t in reads if _index(t) < store]
    after = [t for t in reads if _index(t) > store]
    assert (len(before), len(after)) == (1, 1), (
        f"{ADDON_TASKS} must read the administrator's identities once before "
        "and once after the bind"
    )
    return before[0], after[0]


def _asserts() -> list[dict]:
    return [t for t in _tasks() if "ansible.builtin.assert" in t]


def _issuer_assert() -> dict:
    found = [
        t for t in _asserts() if "wordpress_oidc_local_issuer" in t.get("vars", {})
    ]
    assert len(found) == 1, "one assert must pin the issuer"
    return found[0]


def _foreign_identity_guard() -> dict:
    prior, _ = _identity_reads()
    found = [t for t in _asserts() if prior["register"] in str(t.get("vars", {}))]
    assert len(found) == 1, "one assert must check the identities read before the bind"
    return found[0]


def _email_claim_keycloak_emits() -> str:
    match = EMAIL_CLAIM.search(read_text(str(REALM)))
    assert match, f"{REALM} must map the email user attribute to a claim"
    return match.group("claim")


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


def _keycloak_origin(app: str, key: str) -> str:
    assert (app, key) == ("web-app-keycloak", "url.origin"), (app, key)
    return LOCAL_ORIGIN


class TestSettingsWordPressReceives(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        cache_base._reset()
        self._cwd = str(Path.cwd())
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmpdir.cleanup()
        _reset_cache_for_tests()

    def _settings(self) -> dict:
        sent = _task_running(SETTINGS_WRITE)["environment"]["WP_OIDC_SETTINGS"]
        oidc = load_yaml_any(str(OIDC_VARS), default_if_missing={})["defaults_oidc"]
        encoded = _render(
            sent,
            application_id="web-app-wordpress",
            applications={"web-app-wordpress": {}},
            OIDC=oidc,
        )
        return json.loads(base64.b64decode(encoded))

    def test_the_email_format_reads_the_claim_keycloak_emits(self):
        self.assertEqual(
            self._settings()["email_format"], "{" + _email_claim_keycloak_emits() + "}"
        )

    def test_no_existing_account_is_linked_by_email_or_user_name(self):
        settings = self._settings()
        self.assertIs(settings["link_existing_users"], False)
        self.assertIs(settings["identify_with_username"], False)

    def test_an_unlinked_identity_still_gets_its_own_account(self):
        self.assertIs(self._settings()["create_if_does_not_exist"], True)


class TestIssuerIsTheLocalKeycloak(unittest.TestCase):
    def _passes(self, client: dict) -> bool:
        task = _issuer_assert()
        real_get = lookup_loader.get

        def get(name, *args, **kwargs):
            if name == "tls":
                return _Stub(_keycloak_origin)
            return real_get(name, *args, **kwargs)

        oidc = {"CLIENT": {"REALM": "infinito", **client}}
        with unittest.mock.patch.object(lookup_loader, "get", side_effect=get):
            local = _render(task["vars"]["wordpress_oidc_local_issuer"], OIDC=oidc)
        return all(
            _holds(condition, OIDC=oidc, wordpress_oidc_local_issuer=local)
            for condition in task["ansible.builtin.assert"]["that"]
        )

    def test_the_issuer_is_checked_before_keycloak_is_asked(self):
        index = _index(_issuer_assert())
        names = [str(t.get("name", "")) for t in _tasks()]
        resolver = next(i for i, n in enumerate(names) if "resolve the Keycloak" in n)
        lookup = _index(_task_running("kcadm.sh get users"))
        self.assertLess(index, resolver)
        self.assertLess(index, lookup)

    def test_the_issuer_is_checked_before_the_settings_are_written(self):
        self.assertLess(_index(_issuer_assert()), _index(_task_running(SETTINGS_WRITE)))

    def test_only_the_local_keycloak_passes(self):
        for client, passes in (
            (
                {"ISSUER_URL": LOCAL_ISSUER, "TOKEN_URL": LOCAL_ISSUER + TOKEN_PATH},
                True,
            ),
            (
                {
                    "ISSUER_URL": EXTERNAL_ISSUER,
                    "TOKEN_URL": EXTERNAL_ISSUER + TOKEN_PATH,
                },
                False,
            ),
            (
                {"ISSUER_URL": LOCAL_ISSUER, "TOKEN_URL": EXTERNAL_ISSUER + TOKEN_PATH},
                False,
            ),
            (
                {
                    "ISSUER_URL": LOCAL_ORIGIN + "/realms/other",
                    "TOKEN_URL": LOCAL_ORIGIN + "/realms/other" + TOKEN_PATH,
                },
                False,
            ),
        ):
            with self.subTest(client=client):
                self.assertIs(self._passes(client), passes)


class TestAdministratorSubjectBinding(unittest.TestCase):
    def test_every_deploy_runs_the_bind_on_the_stack_host(self):
        addon_tasks = load_yaml_any(str(ADDON_TASKS_ENTRY), default_if_missing=[])
        includes = [
            t for t in addon_tasks if t.get("include_tasks") == ADDON_TASKS.name
        ]
        self.assertEqual([t.get("when") for t in includes], ["IS_STACK_HOST | bool"])

    def test_the_administrator_is_looked_up_in_keycloak_by_its_user_name(self):
        argv = _argv(
            _task_running("kcadm.sh get users"),
            WORDPRESS_KEYCLOAK_LOCAL_CID="keycloak",
            OIDC={"CLIENT": {"REALM": "infinito"}},
            WORDPRESS_ADMIN_USER=ADMIN,
        )
        script = argv.index("-c") + 1
        query = shlex.split(argv[script].split("&& exec ", 1)[1])
        self.assertEqual(
            query,
            [
                "/opt/keycloak/bin/kcadm.sh",
                "get",
                "users",
                "-r",
                "$1",
                "-q",
                "username=$2",
                "-q",
                "exact=true",
                "--fields",
                "id,username",
            ],
        )
        self.assertEqual(argv[script + 1 :], ["_", "infinito", ADMIN])

    def test_the_keycloak_user_id_is_stored_as_the_administrators_subject(self):
        subject = _admin_subject()
        self.assertEqual(list(subject.values()), [KEYCLOAK_ID])
        argv = _argv(_task_running("wp user meta update"), **WORDPRESS, **subject)
        update = argv.index("update")
        self.assertEqual(argv[update - 2 : update], ["user", "meta"])
        self.assertEqual(
            argv[update + 1 : update + 4], [ADMIN, SUBJECT_META_KEY, KEYCLOAK_ID]
        )


class TestExclusiveBinding(unittest.TestCase):
    def test_every_account_holding_the_id_under_any_key_is_listed(self):
        argv = _argv(_task_running(HOLDERS), **WORDPRESS, **_admin_subject())
        self.assertEqual(
            argv[argv.index("wp") : argv.index("wp") + 3], ["wp", "user", "list"]
        )
        for option in (
            "--blog_id=0",
            f"--meta_key={SUBJECT_META_KEY}",
            "--meta_compare_key=LIKE",
            f"--meta_value={KEYCLOAK_ID}",
        ):
            self.assertIn(option, argv)

    def test_the_keys_of_every_other_holder_are_listed_by_name_only(self):
        listing = _task_running(HOLDERS)
        stray_keys = _task_running(STRAY_KEYS)
        for holders, others in (
            ([{"ID": 1, "user_login": ADMIN}, *OTHER_HOLDERS], OTHER_HOLDERS),
            ([{"ID": 1, "user_login": ADMIN}], []),
            ([{"ID": 1, "user_login": ADMIN.title()}, *OTHER_HOLDERS], OTHER_HOLDERS),
        ):
            listed = {listing["register"]: {"stdout": json.dumps(holders)}}
            with self.subTest(holders=holders):
                self.assertEqual(
                    _render(stray_keys["loop"], **WORDPRESS, **listed), others
                )
        argv = _argv(stray_keys, item=MALLORY, **WORDPRESS)
        self.assertEqual(
            argv[argv.index("meta") + 1 : argv.index("meta") + 3], ["list", "7"]
        )
        self.assertIn("--fields=meta_key", argv)

    def test_only_subject_identity_keys_of_a_holder_are_read(self):
        stray_keys = _task_running(STRAY_KEYS)
        stray_identities = _task_running(STRAY_IDENTITIES)
        self.assertEqual(
            stray_identities["loop"], "{{ " + stray_keys["register"] + ".results }}"
        )
        keys = [
            "session_tokens",
            "openid-connect-generic-last-token-response",
            SITE_PREFIXED,
        ]
        item = {"item": MALLORY, "stdout": json.dumps([{"meta_key": k} for k in keys])}
        argv = _argv(stray_identities, item=item, **WORDPRESS)
        self.assertIn(f"--keys={SUBJECT_META_KEY},{SITE_PREFIXED}", argv)
        self.assertIn("--fields=meta_key,meta_value", argv)

    def test_the_id_is_removed_under_exactly_the_key_that_holds_it(self):
        stray_identities = _task_running(STRAY_IDENTITIES)
        unbind = _task_running(UNBIND)
        results = [
            {
                "item": {"item": MALLORY},
                "stdout": json.dumps(
                    [
                        {"meta_key": SUBJECT_META_KEY, "meta_value": KEYCLOAK_ID},
                        {"meta_key": PREFIXED, "meta_value": OTHER_ID},
                    ]
                ),
            },
            {
                "item": {"item": DUPLICATE},
                "stdout": json.dumps(
                    [{"meta_key": SITE_PREFIXED, "meta_value": KEYCLOAK_ID}]
                ),
            },
        ]
        read = {stray_identities["register"]: {"results": results}}
        pairs = _render(unbind["loop"], **read, **_admin_subject())
        self.assertEqual(
            [(p["ID"], p["meta_key"]) for p in pairs],
            [(7, SUBJECT_META_KEY), (9, SITE_PREFIXED)],
        )
        for pair in pairs:
            argv = _argv(unbind, item=pair, **WORDPRESS, **_admin_subject())
            delete = argv.index("delete")
            self.assertEqual(
                argv[delete + 1 : delete + 4],
                [str(pair["ID"]), pair["meta_key"], KEYCLOAK_ID],
            )
            self.assertEqual(
                _render(unbind["loop_control"]["label"], item=pair),
                f"{pair['user_login']} {pair['meta_key']}",
            )
        self.assertIs(unbind["changed_when"], True)

    def test_the_run_fails_unless_only_the_administrator_holds_the_id(self):
        check = _task_running(OWNERS)
        argv = _argv(check, **WORDPRESS, **_admin_subject())
        for option in (
            "--blog_id=0",
            f"--meta_key={SUBJECT_META_KEY}",
            "--meta_compare_key=LIKE",
            f"--meta_value={KEYCLOAK_ID}",
        ):
            self.assertIn(option, argv)
        for rc, owners, fails in (
            (0, [ADMIN], False),
            (0, [ADMIN.title()], False),
            (0, [ADMIN, "mallory"], True),
            (0, [], True),
            (1, [ADMIN], True),
        ):
            result = {
                "rc": rc,
                "stdout": json.dumps([{"user_login": o} for o in owners]),
            }
            with self.subTest(rc=rc, owners=owners):
                self.assertIs(
                    _holds(
                        check["failed_when"],
                        WORDPRESS_ADMIN_USER=ADMIN,
                        **{check["register"]: result},
                    ),
                    fails,
                )


class TestAdministratorCarriesNoForeignIdentity(unittest.TestCase):
    def _keys_read(self, admin_keys: list[str]) -> list[str]:
        identity_keys = {ADMIN_IDENTITY_KEYS: _identity_keys(admin_keys)}
        read = []
        for check in _identity_reads():
            argv = _argv(check, **WORDPRESS, **identity_keys)
            keys = [a for a in argv if a.startswith("--keys=")]
            self.assertEqual(len(keys), 1)
            self.assertIn("--fields=meta_key,meta_value", argv)
            read.append(keys[0].removeprefix("--keys=").split(","))
        self.assertEqual(read[0], read[1])
        return read[0]

    def _guard(self, rows: list[tuple[str, str]]) -> tuple[bool, str]:
        prior, _ = _identity_reads()
        guard = _foreign_identity_guard()
        variables = {
            **WORDPRESS,
            **_admin_subject(),
            prior["register"]: {
                "rc": 0,
                "stdout": json.dumps(
                    [{"meta_key": k, "meta_value": v} for k, v in rows]
                ),
            },
        }
        variables.update(
            {name: _render(value, **variables) for name, value in guard["vars"].items()}
        )
        check = guard["ansible.builtin.assert"]
        passes = all(_holds(c, **variables) for c in check["that"])
        return passes, _render(check["fail_msg"], **variables)

    def test_the_identities_are_checked_after_the_keys_and_before_the_bind(self):
        prior, verified = _identity_reads()
        self.assertLess(_index(_task_running(ADMIN_KEYS)), _index(prior))
        self.assertLess(_index(prior), _index(_foreign_identity_guard()))
        self.assertLess(_index(_foreign_identity_guard()), _index(_task_running(STORE)))
        self.assertLess(_index(_task_running(STORE)), _index(verified))

    def test_a_foreign_global_identity_stops_the_deploy_before_the_bind(self):
        passes, message = self._guard([(SUBJECT_META_KEY, OTHER_ID)])
        self.assertIs(passes, False)
        self.assertIn(f"under {SUBJECT_META_KEY},", message)
        self.assertIn(f"wp user meta delete {ADMIN} <key>", message)
        self.assertNotIn(OTHER_ID, message)

    def test_every_foreign_key_is_named_without_its_value(self):
        passes, message = self._guard(
            [
                (SUBJECT_META_KEY, KEYCLOAK_ID),
                (PREFIXED, OTHER_ID),
                (SITE_PREFIXED, OTHER_ID),
            ]
        )
        self.assertIs(passes, False)
        self.assertIn(f"under {PREFIXED}, {SITE_PREFIXED},", message)
        self.assertNotIn(OTHER_ID, message)

    def test_an_absent_or_equal_identity_lets_the_bind_run(self):
        for rows in (
            [],
            [(SUBJECT_META_KEY, KEYCLOAK_ID)],
            [(SUBJECT_META_KEY, KEYCLOAK_ID), (PREFIXED, KEYCLOAK_ID)],
        ):
            with self.subTest(rows=rows):
                self.assertIs(self._guard(rows)[0], True)

    def test_only_subject_identity_keys_are_read_and_the_global_one_always(self):
        listing = _task_running(ADMIN_KEYS)
        self.assertIn("--fields=meta_key", _argv(listing, **WORDPRESS))
        for admin_keys, read in (
            (
                [
                    "session_tokens",
                    "openid-connect-generic-last-token-response",
                    SUBJECT_META_KEY,
                    PREFIXED,
                    SITE_PREFIXED,
                ],
                [SUBJECT_META_KEY, PREFIXED, SITE_PREFIXED],
            ),
            (["session_tokens"], [SUBJECT_META_KEY]),
            ([PREFIXED], [SUBJECT_META_KEY, PREFIXED]),
        ):
            with self.subTest(admin_keys=admin_keys):
                self.assertEqual(self._keys_read(admin_keys), read)

    def test_the_run_fails_unless_every_identity_on_the_administrator_is_its_id(self):
        _, check = _identity_reads()
        for rc, rows, fails in (
            (0, [(SUBJECT_META_KEY, KEYCLOAK_ID)], False),
            (0, [(SUBJECT_META_KEY, KEYCLOAK_ID), (PREFIXED, KEYCLOAK_ID)], False),
            (0, [(SUBJECT_META_KEY, KEYCLOAK_ID), (PREFIXED, OTHER_ID)], True),
            (0, [(SUBJECT_META_KEY, KEYCLOAK_ID), (SITE_PREFIXED, OTHER_ID)], True),
            (0, [(PREFIXED, KEYCLOAK_ID)], True),
            (0, [(SUBJECT_META_KEY, OTHER_ID)], True),
            (0, [], True),
            (1, [(SUBJECT_META_KEY, KEYCLOAK_ID)], True),
        ):
            result = {
                "rc": rc,
                "stdout": json.dumps(
                    [{"meta_key": k, "meta_value": v} for k, v in rows]
                ),
            }
            with self.subTest(rc=rc, rows=rows):
                self.assertIs(
                    _holds(
                        check["failed_when"],
                        **_admin_subject(),
                        **{check["register"]: result},
                    ),
                    fails,
                )


if __name__ == "__main__":
    unittest.main()
