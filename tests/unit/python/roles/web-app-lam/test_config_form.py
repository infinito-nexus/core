from __future__ import annotations

import json
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.applications.forms import locks
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

APPLICATION = "web-app-lam"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VARS = ROLE / ROLE_FILE_VARS_MAIN
ENV = ROLE / "templates" / "env.j2"
LOADER = ROLE / "templates" / "javascript.js.j2"
CORE_TASKS = ROLE / "tasks" / "00_core.yml"
DRIFT_READ = ROLE / "tasks" / "01_forms_drift.yml"
SHARED_RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
DRIFT_TASKS = "tasks/utils/forms/drift.yml"
PAGE = "/lam/templates/config/"
ADMIN_VALUE = "admin-value-0"
USERS = {"platform_administrator": {"password": ADMIN_VALUE}}
BASE_DN = "dc=example,dc=test"
FILTER = (
    "(&(uid=%USER%)(memberOf=cn=web-app-lam-administrator,ou=roles,dc=example,dc=test))"
)
PROFILE = {
    "server_url": "ldap",
    "admins": "cn=admin,dc=example,dc=test",
    "base_dn": BASE_DN,
    "language": "en_US.utf8",
    "login_search_suffix": "ou=users,dc=example,dc=test",
    "login_search_filter": FILTER,
}
SINK = {
    "master_login": ADMIN_VALUE,
    "serverurl": "ldap",
    "admins": "cn=admin,dc=example,dc=test",
    "lang": "en_US.utf8",
    "loginSearchSuffix": "ou=users,dc=example,dc=test",
    "loginSearchFilter": FILTER,
    "suffix_user": BASE_DN,
    "suffix_group": BASE_DN,
}
LDAP = {
    "SERVER": {"DOMAIN": "ldap"},
    "DN": {
        "ROOT": BASE_DN,
        "ADMINISTRATOR": {"DATA": "cn=admin,dc=example,dc=test"},
        "OU": {
            "USERS": "ou=users,dc=example,dc=test",
            "ROLES": "ou=roles,dc=example,dc=test",
        },
    },
    "USER": {"ATTRIBUTES": {"ID": "uid", "MEMBER_OF": "memberOf"}},
}
ENV_LINE = re.compile(r"^([A-Z_]+)=(.*)$", re.MULTILINE)
PRETTY_CONF = """{
    "ServerURL": "ldap:\\/\\/edited:389",
    "Passwd": "{SSHA}held-hash",
    "Admins": "cn=admin,dc=example,dc=test",
    "defaultLanguage": "de_DE.utf8",
    "loginSearchSuffix": "ou=users,dc=example,dc=test",
    "loginSearchFilter": "(uid=\\"%USER%\\")",
    "loginSearchPassword": "held-bind-value",
    "typeSettings": {
        "suffix_user": "ou=people,dc=example,dc=test",
        "suffix_group": "dc=example,dc=test"
    }
}
"""
HELD = {
    "serverurl": "ldap://edited:389",
    "admins": "cn=admin,dc=example,dc=test",
    "lang": "de_DE.utf8",
    "loginSearchSuffix": "ou=users,dc=example,dc=test",
    "loginSearchFilter": '(uid="%USER%")',
    "suffix_user": "ou=people,dc=example,dc=test",
    "suffix_group": "dc=example,dc=test",
}


class _Address(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        if list(terms) != [APPLICATION, "lam"]:
            raise AssertionError(f"addressed {terms}")
        return ["lam"]


def _forms() -> dict:
    return load_yaml_any(str(FORMS), default_if_missing={})


def _application() -> dict:
    return {"services": {"lam": {"profile": PROFILE}}}


def _render(expression, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _drift_tasks() -> list[dict]:
    return load_yaml_any(str(DRIFT_READ), default_if_missing=[])


def _held_lines(conf: str) -> list[str]:
    read = _drift_tasks()[0]
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "container_address":
            return _Address()
        return real_get(name, *args, **kwargs)

    variables = load_yaml_any(str(VARS))
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        command = _render(
            read["ansible.builtin.shell"]["cmd"],
            application_id=APPLICATION,
            LAM_CONFIG_PROFILE_FIELDS=variables["LAM_CONFIG_PROFILE_FIELDS"],
            LAM_CONFIG_PROFILE_FILE=variables["LAM_CONFIG_PROFILE_FILE"],
            LAM_CONFIG_PROFILE_VALUE=variables["LAM_CONFIG_PROFILE_VALUE"],
        )
    argv = shlex.split(command)
    if argv[:3] != ["container", "exec", "lam"]:
        raise AssertionError(f"the read runs {argv[:3]}")
    with tempfile.TemporaryDirectory() as tmp:
        conf_path = Path(tmp) / "lam.conf"
        conf_path.write_text(conf, encoding="utf-8")
        result = subprocess.run(
            [*argv[3:-1], str(conf_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    return result.stdout.splitlines()


class TestConfigForm(unittest.TestCase):
    def test_the_computed_profile_keeps_the_values_the_role_wrote(self) -> None:
        services = DataLoader().load_from_file(str(SERVICES), trusted_as_template=True)
        self.assertEqual(
            PROFILE,
            Templar(loader=DataLoader(), variables={"LDAP": LDAP}).template(
                services["lam"]["profile"]
            ),
        )

    def test_the_form_carries_every_managed_setting(self) -> None:
        self.assertEqual(
            SINK, values("config", _forms(), _application(), USERS, "enforced")
        )

    def test_the_renderer_locks_every_setting_on_the_config_pages(self) -> None:
        fields = _forms()["config"]["fields"]
        found = locks(APPLICATION, _forms(), _application(), USERS, {})
        self.assertEqual(
            [
                (PAGE, spec["selector"], spec["type"] == "password")
                for spec in fields.values()
            ],
            [(lock["page"], lock["selector"], lock["secret"]) for lock in found],
        )
        self.assertEqual(list(SINK), list(fields))
        self.assertEqual(
            "#masterpassword, #masterpassword2, #passwd1, #passwd2",
            fields["master_login"]["selector"],
        )
        services = load_yaml_any(str(SERVICES))
        self.assertIs(True, services["javascript"]["enabled"])
        self.assertIn(SHARED_RENDERER, read_text(str(LOADER)))

    def test_the_sink_reads_only_the_config_form(self) -> None:
        variables = load_yaml_any(str(VARS))
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'config') }}",
            variables["LAM_CONFIG"],
        )
        self.assertEqual(
            ADMIN_VALUE, _render(variables["LAM_PASSWORD"], LAM_CONFIG=SINK)
        )

    def test_the_env_writes_every_managed_setting_from_the_sink(self) -> None:
        lines = dict(ENV_LINE.findall(read_text(str(ENV))))
        managed = {
            "LAM_PASSWORD": f'"{ADMIN_VALUE}"',
            "LAM_LANG": "en_US",
            "LDAP_SERVER": "ldap",
            "LDAP_USER": "cn=admin,dc=example,dc=test",
            "LDAP_USERS_DN": BASE_DN,
            "LDAP_GROUPS_DN": BASE_DN,
            "LAM_LOGIN_SEARCH_SUFFIX": '"ou=users,dc=example,dc=test"',
            "LAM_LOGIN_SEARCH_FILTER": json.dumps(FILTER),
        }
        self.assertEqual(
            managed,
            {
                name: _render(
                    lines[name],
                    LAM_CONFIG=SINK,
                    LAM_PASSWORD=ADMIN_VALUE,
                    LDAP={"SERVER": {"DOMAIN": "stale"}},
                )
                for name in managed
            },
        )

    def test_the_drift_read_takes_only_the_managed_settings(self) -> None:
        for conf in (PRETTY_CONF, json.dumps(json.loads(PRETTY_CONF))):
            with self.subTest(pretty=conf == PRETTY_CONF):
                lines = _held_lines(conf)
                self.assertEqual(7, len(lines))
                held = "\n".join(lines)
                self.assertNotIn("held-hash", held)
                self.assertNotIn("held-bind-value", held)
                report = _drift_tasks()[1]
                profile = _render(
                    report["vars"]["lam_config_profile"],
                    lam_config_held={"stdout_lines": lines},
                )
                self.assertEqual(
                    HELD,
                    _render(
                        report["vars"]["forms_drift_current"]["config"],
                        lam_config_profile=profile,
                        LAM_CONFIG_PROFILE_FIELDS=load_yaml_any(str(VARS))[
                            "LAM_CONFIG_PROFILE_FIELDS"
                        ],
                    ),
                )

    def test_the_drift_report_skips_a_missing_container(self) -> None:
        read, report = _drift_tasks()
        self.assertEqual("lam_config_held", read["register"])
        self.assertIs(False, read["failed_when"])
        self.assertIs(False, read["changed_when"])
        self.assertIn(DRIFT_TASKS, report["ansible.builtin.include_tasks"])
        self.assertEqual("lam_config_held.rc == 0", report["when"])

    def test_the_drift_report_runs_before_the_container_start(self) -> None:
        tasks = load_yaml_any(str(CORE_TASKS), default_if_missing=[])
        names = [
            str(task.get("ansible.builtin.include_tasks") or task.get("include_role"))
            for task in tasks
        ]
        drift = names.index("01_forms_drift.yml")
        stack = next(index for index, name in enumerate(names) if "svc-stack" in name)
        self.assertLess(drift, stack)


if __name__ == "__main__":
    unittest.main()
