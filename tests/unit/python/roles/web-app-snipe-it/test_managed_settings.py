from __future__ import annotations

import re
import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/web-app-snipe-it"
APPLIER = ROLE / "files/php/apply/settings.php"
CREDENTIAL_SCRIPT = ROLE / "files/php/apply/ldap_config.php"
DRIFT = "{{ lookup('path_absolute', 'tasks/utils/forms/drift.yml') }}"
ADMIN = "administrator"
LDAP = {
    "SERVER": {"URI": "ldap://ldap.example.test:389", "PORT": 389},
    "DN": {
        "ADMINISTRATOR": {"DATA": "cn=admin,dc=example,dc=test"},
        "OU": {
            "USERS": "ou=users,dc=example,dc=test",
            "ROLES": "ou=roles,dc=example,dc=test",
        },
    },
    "USER": {
        "ATTRIBUTES": {
            "ID": "uid",
            "FIRSTNAME": "givenName",
            "SURNAME": "sn",
            "MAIL": "mail",
            "MEMBER_OF": "memberOf",
            "DISPLAY_NAME": "displayName",
            "EMPLOYEE_NUMBER": "employeeNumber",
            "PHONE": "telephoneNumber",
            "MOBILE": "mobile",
            "TITLE": "title",
            "DEPARTMENT": "departmentNumber",
            "STREET": "street",
            "LOCALITY": "l",
            "REGION": "st",
            "POSTAL_CODE": "postalCode",
            "COUNTRY": "c",
        }
    },
}
OIDC = {
    "CLIENT": {
        "RESET_CREDENTIALS": "https://auth.example.test/reset",
        "LOGOUT_URL": "https://auth.example.test/logout",
    }
}
COLUMN_WRITE = re.compile(r"->([a-z_]+)\s*=(?!=)")
SPEC_FIELD_MAP = re.compile(r"const SNIPE_IT_FIELD_BY_SETTING = \{(.*?)\};", re.DOTALL)
SPEC_SETTING = re.compile(r"^\s*(ldap_[a-z_]+):", re.MULTILINE)


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


def _forms() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})


def _tasks(name: str) -> list[dict]:
    return load_yaml_any(str(ROLE / "tasks" / name), default_if_missing=[])


def _task(name: str, fragment: str) -> dict:
    return next(task for task in _tasks(name) if fragment in task["name"])


def _position(name: str, fragment: str) -> int:
    return next(i for i, task in enumerate(_tasks(name)) if fragment in task["name"])


def _templated(node, variables: dict, stubs: dict):
    real_get = lookup_loader.get

    def get(lookup_name, *args, **kwargs):
        if lookup_name in stubs:
            return _Stub(stubs[lookup_name])
        return real_get(lookup_name, *args, **kwargs)

    templar = Templar(loader=DataLoader(), variables=variables)
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(node)


def _rendered_settings() -> dict:
    declared = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
    )
    users = {"platform_administrator": {"username": ADMIN}}
    return _templated(
        {key: declared["snipe-it"][key] for key in ("ldap", "remote_user")},
        {"LDAP": LDAP, "OIDC": OIDC},
        {"users": lambda key: users[key]},
    )


def _sink(name: str, ldap: bool = True, sso: bool = True):
    application = {
        "services": {
            "ldap": {"enabled": ldap},
            "sso": {"enabled": sso},
            "snipe-it": _rendered_settings(),
        }
    }
    forms = _forms()
    declared = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
    )
    return _templated(
        declared[name],
        {**declared, "application_id": "web-app-snipe-it"},
        {"form_values": lambda _app, form: values(form, forms, application, {})},
    )


class TestSinks(unittest.TestCase):
    def test_the_ldap_sink_carries_every_ldap_field_while_ldap_is_on(self):
        self.assertEqual(
            list(_forms()["ldap"]["fields"]), list(_sink("SNIPE_IT_LDAP_SETTINGS"))
        )

    def test_the_ldap_sink_is_empty_while_ldap_is_off(self):
        self.assertEqual({}, _sink("SNIPE_IT_LDAP_SETTINGS", ldap=False))

    def test_the_remote_user_sink_follows_sso(self):
        self.assertEqual(
            list(_forms()["remote_user"]["fields"]),
            list(_sink("SNIPE_IT_REMOTE_USER_SETTINGS")),
        )
        self.assertEqual({}, _sink("SNIPE_IT_REMOTE_USER_SETTINGS", sso=False))

    def test_the_switches_reach_snipe_it_as_the_integers_it_stores(self):
        self.assertEqual(1, _sink("SNIPE_IT_LDAP_SETTINGS")["ldap_enabled"])
        remote_user = _sink("SNIPE_IT_REMOTE_USER_SETTINGS")
        self.assertEqual(1, remote_user["login_remote_user_enabled"])
        self.assertEqual(0, remote_user["login_common_disabled"])

    def test_the_directory_values_render_from_the_ldap_attributes(self):
        settings = _sink("SNIPE_IT_LDAP_SETTINGS")
        self.assertEqual(LDAP["SERVER"]["URI"], settings["ldap_server"])
        self.assertEqual("givenname", settings["ldap_fname_field"])
        self.assertEqual("sn", settings["ldap_lname_field"])
        self.assertEqual("uid=", settings["ldap_auth_filter_query"])
        self.assertEqual(
            OIDC["CLIENT"]["RESET_CREDENTIALS"], settings["custom_forgot_pass_url"]
        )

    def test_the_filter_admits_both_role_groups_and_leaves_out_the_bootstrap_admin(
        self,
    ):
        roles = LDAP["DN"]["OU"]["ROLES"]
        self.assertEqual(
            "&(objectClass=inetOrgPerson)"
            f"(|(memberOf=cn=web-app-snipe-it-administrator,{roles})"
            f"(memberOf=cn=web-app-snipe-it-user,{roles}))"
            f"(!(uid={ADMIN}))",
            _sink("SNIPE_IT_LDAP_SETTINGS")["ldap_filter"],
        )

    def test_the_remote_user_logout_leads_to_the_central_end_session(self):
        self.assertEqual(
            OIDC["CLIENT"]["LOGOUT_URL"],
            _sink("SNIPE_IT_REMOTE_USER_SETTINGS")[
                "login_remote_user_custom_logout_url"
            ],
        )


class TestFieldMap(unittest.TestCase):
    def test_every_profile_column_is_a_field_of_the_ldap_form(self):
        columns = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))[
            "SNIPE_IT_LDAP_PROFILE_COLUMNS"
        ]
        self.assertLessEqual(set(columns), set(_forms()["ldap"]["fields"]))

    def test_the_field_map_holds_exactly_the_profile_columns(self):
        columns = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))[
            "SNIPE_IT_LDAP_PROFILE_COLUMNS"
        ]
        self.assertEqual(sorted(columns), sorted(_sink("SNIPE_IT_LDAP_FIELD_MAP")))
        self.assertEqual({}, _sink("SNIPE_IT_LDAP_FIELD_MAP", ldap=False))

    def test_the_field_map_holds_the_directory_settings_the_rbac_spec_writes(self):
        block = SPEC_FIELD_MAP.search(
            read_text(str(ROLE / "files/playwright/test-rbac.js"))
        )
        self.assertIsNotNone(
            block, "test-rbac.js must declare SNIPE_IT_FIELD_BY_SETTING"
        )
        written = {*SPEC_SETTING.findall(block.group(1)), "ldap_dept"}
        self.assertEqual(written, set(_sink("SNIPE_IT_LDAP_FIELD_MAP")))


class TestConverge(unittest.TestCase):
    CASES = (
        ("02_ldap.yml", "LDAP", "ldap", "SNIPE_IT_LDAP_SETTINGS"),
        ("04_sso.yml", "remote user", "remote_user", "SNIPE_IT_REMOTE_USER_SETTINGS"),
    )

    def test_the_drift_report_runs_between_the_read_and_the_write(self):
        for tasks, label, _form, _sink_name in self.CASES:
            with self.subTest(tasks=tasks):
                self.assertLess(
                    _position(tasks, f"read the stored {label} settings"),
                    _position(tasks, f"report the managed {label} settings"),
                )
                self.assertLess(
                    _position(tasks, f"report the managed {label} settings"),
                    _position(tasks, f"write the managed {label} settings"),
                )

    def test_the_read_and_the_write_hand_the_applier_the_same_sink(self):
        for tasks, label, _form, sink in self.CASES:
            for step, mode in (
                ("read the stored", "read"),
                ("write the managed", "write"),
            ):
                with self.subTest(tasks=tasks, mode=mode):
                    task = _task(tasks, f"{step} {label} settings")
                    self.assertIn(
                        f"-e SNIPE_IT_SETTINGS_MODE={mode}",
                        task["ansible.builtin.shell"]["cmd"],
                    )
                    self.assertIn(
                        f"-e SNIPE_IT_SETTINGS={{{{ {sink} | to_json | b64encode | quote }}}}",
                        task["ansible.builtin.shell"]["cmd"],
                    )
                    self.assertEqual(
                        "{{ lookup('file', 'php/apply/settings.php') }}",
                        task["ansible.builtin.shell"]["stdin"],
                    )

    def test_the_drift_report_names_the_form_the_read_covers(self):
        for tasks, label, form, _sink_name in self.CASES:
            with self.subTest(tasks=tasks):
                task = _task(tasks, f"report the managed {label} settings")
                self.assertEqual(DRIFT, task["include_tasks"])
                register = _task(tasks, f"read the stored {label} settings")["register"]
                self.assertEqual(
                    f"{{{{ {{'{form}': {register}.stdout | from_json}} }}}}",
                    task["vars"]["forms_drift_current"],
                )

    def test_the_read_changes_nothing_and_the_write_reports_its_change(self):
        for tasks, label, _form, _sink_name in self.CASES:
            with self.subTest(tasks=tasks):
                self.assertIs(
                    False,
                    _task(tasks, f"read the stored {label} settings")["changed_when"],
                )
                write = _task(tasks, f"write the managed {label} settings")
                self.assertEqual(
                    f"{write['register']}.stdout | trim == 'changed'",
                    write["changed_when"],
                )

    def test_the_write_runs_only_while_a_managed_field_drifted(self):
        for tasks, label, _form, _sink_name in self.CASES:
            register = _task(tasks, f"read the stored {label} settings")["register"]
            when = _task(tasks, f"write the managed {label} settings")["when"]
            for stdout, runs in (("{}", False), ('{"ldap_server": null}', True)):
                with self.subTest(tasks=tasks, stdout=stdout):
                    self.assertIs(
                        runs,
                        _templated(
                            _trust_as_template("{{ (" + when + ") | bool }}"),
                            {register: {"stdout": stdout}},
                            {},
                        ),
                    )

    def test_the_remote_user_caches_clear_only_after_a_write(self):
        task = _task("04_sso.yml", "clear Laravel caches")
        written = _task("04_sso.yml", "write the managed remote user settings")
        self.assertEqual(f"{written['register']} is changed", task["when"])

    def test_the_ldap_caches_clear_only_after_a_write_or_a_credential_change(self):
        written = _task("02_ldap.yml", "write the managed LDAP settings")["register"]
        credential = _task("02_ldap.yml", "apply the LDAP port and bind credential")
        self.assertEqual(
            f"{credential['register']}.stdout | trim == 'changed'",
            credential["changed_when"],
        )
        self.assertEqual(
            f"{written} is changed or {credential['register']} is changed",
            _task("02_ldap.yml", "clear Laravel caches")["when"],
        )

    def test_the_credential_script_writes_no_declared_field(self):
        declared = {field for block in _forms().values() for field in block["fields"]}
        written = set(COLUMN_WRITE.findall(read_text(str(CREDENTIAL_SCRIPT))))
        self.assertEqual({"ldap_port", "ldap_version", "ldap_pword"}, written)
        self.assertFalse(written & declared)

    def test_the_applier_writes_only_through_its_input(self):
        self.assertEqual([], COLUMN_WRITE.findall(read_text(str(APPLIER))))


if __name__ == "__main__":
    unittest.main()
