from __future__ import annotations

import base64
import json
import os
import re
import shlex
import tempfile
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader
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
ADMIN = "platformadmin"
KEYCLOAK_ID = "6f1c0d3e-8b5a-4f0e-9d2c-1a7b3c5e9f00"
KCADM_USERS = [
    {"id": "decoy-id", "username": ADMIN + "2"},
    {"id": KEYCLOAK_ID, "username": ADMIN},
]
OTHER_HOLDERS = [
    {"ID": 7, "user_login": "mallory"},
    {"ID": 9, "user_login": ADMIN + "2"},
]
WORDPRESS = {
    "WORDPRESS_USER": "www-data",
    "WORDPRESS_CONTAINER_ADDRESS": "wordpress",
    "WORDPRESS_ADMIN_USER": ADMIN,
    "WORDPRESS_DOCKER_HTML_PATH": "/var/www/html",
}

filter_loader.add_directory(str(ROLE / "filter_plugins"))


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _task_running(fragment: str) -> dict:
    tasks = load_yaml_any(str(ADDON_TASKS), default_if_missing=[])
    matches = [t for t in tasks if fragment in str(t.get("ansible.builtin.shell", ""))]
    assert len(matches) == 1, f"{ADDON_TASKS} must run '{fragment}' in exactly one task"
    return matches[0]


def _argv(task: dict, **variables) -> list[str]:
    return shlex.split(_render(task["ansible.builtin.shell"], **variables))


def _admin_subject() -> dict:
    lookup = _task_running("kcadm.sh get users")
    tasks = load_yaml_any(str(ADDON_TASKS), default_if_missing=[])
    facts = [
        t["ansible.builtin.set_fact"] for t in tasks if "ansible.builtin.set_fact" in t
    ]
    assert len(facts) == 1, f"{ADDON_TASKS} must pick the subject in one set_fact"
    kcadm = {lookup["register"]: {"stdout": json.dumps(KCADM_USERS)}}
    return {
        name: _render(expression, WORDPRESS_ADMIN_USER=ADMIN, **kcadm)
        for name, expression in facts[0].items()
    }


def _email_claim_keycloak_emits() -> str:
    match = EMAIL_CLAIM.search(read_text(str(REALM)))
    assert match, f"{REALM} must map the email user attribute to a claim"
    return match.group("claim")


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
        sent = _task_running("wp eval-file")["environment"]["WP_OIDC_SETTINGS"]
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
        self.assertIs(self._settings()["link_existing_users"], False)

    def test_an_unlinked_identity_still_gets_its_own_account(self):
        self.assertIs(self._settings()["create_if_does_not_exist"], True)


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
    def test_every_account_holding_the_id_is_listed(self):
        argv = _argv(
            _task_running("--fields=ID,user_login"), **WORDPRESS, **_admin_subject()
        )
        self.assertEqual(
            argv[argv.index("wp") : argv.index("wp") + 3], ["wp", "user", "list"]
        )
        for option in (
            "--blog_id=0",
            f"--meta_key={SUBJECT_META_KEY}",
            f"--meta_value={KEYCLOAK_ID}",
        ):
            self.assertIn(option, argv)

    def test_the_id_is_removed_from_every_other_holder_only(self):
        listing = _task_running("--fields=ID,user_login")
        unbind = _task_running("wp user meta delete")
        for holders, others in (
            ([{"ID": 1, "user_login": ADMIN}, *OTHER_HOLDERS], OTHER_HOLDERS),
            ([{"ID": 1, "user_login": ADMIN}], []),
        ):
            listed = {listing["register"]: {"stdout": json.dumps(holders)}}
            with self.subTest(holders=holders):
                self.assertEqual(_render(unbind["loop"], **WORDPRESS, **listed), others)
        for holder in OTHER_HOLDERS:
            argv = _argv(unbind, item=holder, **WORDPRESS, **_admin_subject())
            delete = argv.index("delete")
            self.assertEqual(
                argv[delete + 1 : delete + 4],
                [str(holder["ID"]), SUBJECT_META_KEY, KEYCLOAK_ID],
            )
            self.assertEqual(
                _render(unbind["loop_control"]["label"], item=holder),
                holder["user_login"],
            )
        self.assertIs(unbind["changed_when"], True)

    def test_the_run_fails_unless_only_the_administrator_holds_the_id(self):
        check = _task_running("--meta_compare_key=LIKE")
        argv = _argv(check, **WORDPRESS, **_admin_subject())
        for option in (
            "--blog_id=0",
            f"--meta_key={SUBJECT_META_KEY}",
            f"--meta_value={KEYCLOAK_ID}",
        ):
            self.assertIn(option, argv)
        for rc, owners, fails in (
            (0, [ADMIN], False),
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
                    _render(
                        "{{ " + check["failed_when"] + " }}",
                        WORDPRESS_ADMIN_USER=ADMIN,
                        **{check["register"]: result},
                    ),
                    fails,
                )


if __name__ == "__main__":
    unittest.main()
