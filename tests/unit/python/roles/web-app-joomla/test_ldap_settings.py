from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles/web-app-joomla"
TASKS = "10_ldap.yml"
DRIFT = "{{ lookup('path_absolute', 'tasks/utils/forms/drift.yml') }}"
SCOPE = 'form:has([name="jform[params][search_string]"]) '
LDAP = {
    "BIND_CREDENTIAL": "ldap-bind-secret",
    "SERVER": {
        "DOMAIN": "ldap.example.test",
        "PORT": 389,
        "URI": "ldap://ldap.example.test:389",
        "SECURITY": "",
    },
    "DN": {
        "ADMINISTRATOR": {"DATA": "cn=admin,dc=example,dc=test"},
        "OU": {"USERS": "ou=users,dc=example,dc=test"},
    },
    "USER": {"ATTRIBUTES": {"ID": "uid", "FULLNAME": "cn", "MAIL": "mail"}},
}


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


def _form() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})[
        "ldap"
    ]


def _tasks() -> list[dict]:
    return load_yaml_any(str(ROLE / "tasks" / TASKS), default_if_missing=[])


def _task(fragment: str) -> dict:
    return next(task for task in _tasks() if fragment in task["name"])


def _position(fragment: str) -> int:
    return next(i for i, task in enumerate(_tasks()) if fragment in task["name"])


def _templated(node, variables: dict, stubs: dict):
    real_get = lookup_loader.get

    def get(lookup_name, *args, **kwargs):
        if lookup_name in stubs:
            return _Stub(stubs[lookup_name])
        return real_get(lookup_name, *args, **kwargs)

    templar = Templar(loader=DataLoader(), variables=variables)
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(node)


def _sink(ldap_login: bool = True, server: dict | None = None):
    directory = {**LDAP, "SERVER": {**LDAP["SERVER"], **(server or {})}}
    declared = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
    )
    application = {
        "services": {
            "joomla": {
                "login": {"method": {"ldap": {"enabled": ldap_login}}},
                "ldap": _templated(declared["joomla"]["ldap"], {"LDAP": directory}, {}),
            }
        }
    }
    forms = {"ldap": _form()}
    sinks = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
    )
    return _templated(
        sinks["JOOMLA_LDAP_PARAMS"],
        {**sinks, "application_id": "web-app-joomla"},
        {"form_values": lambda _app, form: values(form, forms, application, {})},
    )


def _stored(settings: dict, hidden: int, noise: str = "") -> dict:
    report = json.dumps({"settings": settings, "hidden": hidden})
    return {"joomla_ldap_stored": {"stdout_lines": [*noise.splitlines(), report]}}


class TestSink(unittest.TestCase):
    def test_the_sink_carries_every_field_while_the_ldap_login_is_on(self):
        self.assertEqual(list(_form()["fields"]), list(_sink()))

    def test_the_sink_is_empty_while_the_ldap_login_is_off(self):
        self.assertEqual({}, _sink(ldap_login=False))

    def test_the_parameters_keep_the_values_the_plugin_expects(self):
        self.assertEqual(
            {
                "host": "ldap.example.test",
                "port": 389,
                "use_ldapV3": "1",
                "encryption": "none",
                "no_referrals": "0",
                "auth_method": "search",
                "base_dn": "ou=users,dc=example,dc=test",
                "search_string": "uid=[search]",
                "users_dn": "[username]",
                "username": "cn=admin,dc=example,dc=test",
                "ldap_fullname": "cn",
                "ldap_email": "mail",
                "ldap_uid": "uid",
            },
            dict(_sink()),
        )

    def test_the_encryption_follows_the_directory_transport(self):
        for server, expected in (
            ({"URI": "ldaps://ldap.example.test:636"}, "ssl"),
            ({"SECURITY": "TLS"}, "tls"),
            ({}, "none"),
        ):
            with self.subTest(server=server):
                self.assertEqual(expected, _sink(server=server)["encryption"])

    def test_no_credential_reaches_the_sink(self):
        self.assertNotIn("password", _sink())
        self.assertNotIn(LDAP["BIND_CREDENTIAL"], json.dumps(_sink()))


class TestLock(unittest.TestCase):
    def test_every_field_is_locked_only_on_the_ldap_plugin_page(self):
        for field, spec in _form()["fields"].items():
            with self.subTest(field=field):
                target = f'[name="jform[params][{field}]"]'
                self.assertEqual(
                    target if field == "search_string" else SCOPE + target,
                    spec["selector"],
                )


class TestConverge(unittest.TestCase):
    def test_the_drift_report_runs_between_the_read_and_the_write(self):
        self.assertLess(_position("Read the stored"), _position("Report the"))
        self.assertLess(_position("Report the"), _position("Converge the core LDAP"))

    def test_the_read_and_the_write_hand_the_script_the_same_input(self):
        read = _task("Read the stored")
        write = _task("Converge the core LDAP")
        self.assertIn("-e J_LDAP_MODE=read", read["ansible.builtin.shell"])
        self.assertEqual(
            read["ansible.builtin.shell"].replace(
                "J_LDAP_MODE=read", "J_LDAP_MODE=write"
            ),
            write["ansible.builtin.shell"],
        )
        self.assertEqual(read["args"], write["args"])
        self.assertIs(False, read["changed_when"])
        self.assertEqual(read["no_log"], write["no_log"])

    def test_the_drift_report_names_the_ldap_form(self):
        task = _task("Report the")
        self.assertEqual(DRIFT, task["include_tasks"])
        self.assertEqual(
            {"ldap": {"host": "old"}},
            _templated(
                _trust_as_template(task["vars"]["forms_drift_current"]),
                _stored({"host": "old"}, 0, "Deprecated: noise\n"),
                {},
            ),
        )

    def test_the_write_runs_only_while_a_parameter_or_the_hidden_state_differs(self):
        when = _task("Converge the core LDAP")["when"]
        for stored, runs in (
            (_stored({}, 0), False),
            (_stored({}, 0, "Deprecated: noise\n"), False),
            (_stored({"port": "636"}, 0), True),
            (_stored({}, 1), True),
        ):
            with self.subTest(stored=stored):
                self.assertIs(
                    runs,
                    _templated(
                        _trust_as_template("{{ (" + when + ") | bool }}"), stored, {}
                    ),
                )

    def test_the_cache_clears_only_after_a_write(self):
        self.assertEqual(
            "joomla_ldap_plugin is changed", _task("Clear the Joomla cache")["when"]
        )


@unittest.skipIf(shutil.which("bash") is None, "bash is not installed")
class TestBindCredentialHandOver(unittest.TestCase):
    def _run(self, fragment: str, ldap_login: bool) -> subprocess.CompletedProcess:
        task = _task(fragment)
        variables = {
            "JOOMLA_WEB_USER": "www-data",
            "JOOMLA_DOCROOT": "/var/www/html",
            "JOOMLA_LDAP_ENABLED": ldap_login,
            "JOOMLA_LDAP_PARAMS": {},
            "JOOMLA_LOCAL_CID": "joomla",
            "LDAP": LDAP,
            "role_path": str(ROLE),
        }
        command = _templated(
            _trust_as_template(task["ansible.builtin.shell"]), variables, {}
        )
        stdin = _templated(_trust_as_template(task["args"]["stdin"]), variables, {})
        with tempfile.TemporaryDirectory() as bin_dir:
            stub = Path(bin_dir) / "container"
            stub.write_text('#!/bin/sh\nprintf "<%s>" "$J_LDAP_BIND_PASSWORD"\n')
            stub.chmod(0o755)
            return subprocess.run(
                ["bash", "-c", command],
                input=stdin + "\n",
                env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
                check=False,
            )

    def test_the_plugin_gets_the_credential_only_while_the_ldap_login_is_on(self):
        for fragment in ("Read the stored", "Converge the core LDAP"):
            for ldap_login, handed in (
                (False, "<>"),
                (True, f"<{LDAP['BIND_CREDENTIAL']}>"),
            ):
                with self.subTest(task=fragment, ldap_login=ldap_login):
                    result = self._run(fragment, ldap_login=ldap_login)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(handed, result.stdout)


if __name__ == "__main__":
    unittest.main()
