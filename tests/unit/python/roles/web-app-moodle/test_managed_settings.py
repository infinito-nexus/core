from __future__ import annotations

import base64
import json
import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles/web-app-moodle"
DRIFT = "{{ lookup('path_absolute', 'tasks/utils/forms/drift.yml') }}"
ROLES_OU = "ou=roles,dc=example,dc=test"
SCOPES = "openid profile email moodle"
CREDENTIALS = {"auth_oidc": {"clientsecret"}, "auth_ldap": {"bind_pw"}}
OIDC = {
    "BUTTON_TEXT": "Sign in",
    "CLIENT": {
        "ID": "moodle",
        "SECRET": "oidc-client-secret",
        "AUTHORIZE_URL": "https://auth.example.test/auth",
        "TOKEN_URL": "https://auth.example.test/token",
        "LOGOUT_URL": "https://auth.example.test/logout",
    },
    "ATTRIBUTES": {
        "USERNAME": "preferred_username",
        "GIVEN_NAME": "given_name",
        "FAMILY_NAME": "family_name",
        "MIDDLE_NAME": "middle_name",
        "NICKNAME": "nickname",
        "EMAIL": "email",
        "PHONE_NUMBER": "phone_number",
        "WEBSITE": "website",
        "LOCALE": "locale",
        "ZONEINFO": "zoneinfo",
    },
}
LDAP = {
    "BIND_CREDENTIAL": "ldap-bind-secret",
    "SERVER": {"URI": "ldap://ldap.example.test:389"},
    "DN": {
        "ADMINISTRATOR": {"DATA": "cn=admin,dc=example,dc=test"},
        "OU": {"USERS": "ou=users,dc=example,dc=test", "ROLES": ROLES_OU},
    },
    "FILTERS": {"USERS": {"ALL": "inetOrgPerson"}},
    "RBAC": {"MEMBER_ATTRIBUTE": "member"},
    "USER": {
        "ATTRIBUTES": {
            "ID": "uid",
            "FIRSTNAME": "givenName",
            "SURNAME": "sn",
            "INITIALS": "initials",
            "DISPLAY_NAME": "displayName",
            "MAIL": "mail",
            "PHONE": "telephoneNumber",
            "MOBILE": "mobile",
            "STREET": "street",
            "LOCALITY": "l",
            "COUNTRY": "c",
            "ORGANIZATION": "o",
            "DEPARTMENT": "departmentNumber",
            "DESCRIPTION": "description",
            "EMPLOYEE_NUMBER": "employeeNumber",
            "WEBSITE": "labeledURI",
            "LOCALE": "preferredLanguage",
            "PHONETIC_GIVEN": "givenNamePhonetic",
            "PHONETIC_FAMILY": "snPhonetic",
            "TIMEZONE": "timezone",
        }
    },
}
PROFILE_FIELDS = (
    "firstname",
    "lastname",
    "middlename",
    "alternatename",
    "email",
    "phone1",
    "phone2",
    "address",
    "city",
    "country",
    "institution",
    "department",
    "description",
    "idnumber",
    "url",
    "lang",
    "timezone",
    "firstnamephonetic",
    "lastnamephonetic",
)
CASES = (
    ("04_oidc.yml", "auth_oidc", "MOODLE_OIDC_SETTINGS", {"clientsecret", "oidcscope"}),
    (
        "06_ldap_sync.yml",
        "auth_ldap",
        "MOODLE_LDAP_SETTINGS",
        {"bind_pw", "removecontexts"},
    ),
)


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
    return _templated(
        {key: declared["moodle"][key] for key in ("auth_oidc", "auth_ldap")},
        {"LDAP": LDAP, "OIDC": OIDC},
        {},
    )


def _render(node, ldap: bool = True, sso: bool = True):
    application = {
        "services": {
            "ldap": {"enabled": ldap},
            "sso": {"enabled": sso},
            "moodle": _rendered_settings(),
        }
    }
    forms = _forms()
    declared = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
    )
    return _templated(
        _trust_as_template(node) if isinstance(node, str) else node,
        {
            **declared,
            "application_id": "web-app-moodle",
            "OIDC": OIDC,
            "LDAP": LDAP,
            "MOODLE_OIDC_SCOPES": SCOPES,
            "MOODLE_OIDC_ENABLED": sso,
            "MOODLE_LDAP_ENABLED": ldap,
        },
        {"form_values": lambda _app, form: values(form, forms, application, {})},
    )


def _sink(name: str, ldap: bool = True, sso: bool = True):
    return _render("{{ " + name + " }}", ldap=ldap, sso=sso)


def _stored(settings: dict, hidden: int, noise: str = "") -> dict:
    report = json.dumps({"settings": settings, "hidden": hidden})
    return {
        "moodle_plugin_form_stored": {"stdout_lines": [*noise.splitlines(), report]}
    }


class TestSinks(unittest.TestCase):
    def test_each_sink_carries_every_field_of_its_form_while_its_service_is_on(self):
        for _tasks_file, form, sink, _hidden in CASES:
            with self.subTest(form=form):
                self.assertEqual(list(_forms()[form]["fields"]), list(_sink(sink)))

    def test_each_sink_is_empty_while_its_service_is_off(self):
        self.assertEqual({}, _sink("MOODLE_OIDC_SETTINGS", sso=False))
        self.assertEqual({}, _sink("MOODLE_LDAP_SETTINGS", ldap=False))

    def test_every_value_is_a_string_or_an_integer_the_applier_accepts(self):
        for _tasks_file, form, sink, _hidden in CASES:
            for name, value in _sink(sink).items():
                with self.subTest(form=form, name=name):
                    self.assertIsInstance(value, (str, int))
                    self.assertNotIsInstance(value, bool)

    def test_no_credential_reaches_a_sink(self):
        rendered = json.dumps(
            [_sink("MOODLE_OIDC_SETTINGS"), _sink("MOODLE_LDAP_SETTINGS")]
        )
        self.assertNotIn(OIDC["CLIENT"]["SECRET"], rendered)
        self.assertNotIn(LDAP["BIND_CREDENTIAL"], rendered)

    def test_every_profile_field_is_mapped_locked_and_refreshed_by_both_plugins(self):
        for sink, update in (
            ("MOODLE_OIDC_SETTINGS", "oneveryloginupdate"),
            ("MOODLE_LDAP_SETTINGS", "onlogin"),
        ):
            settings = _sink(sink)
            for field in PROFILE_FIELDS:
                with self.subTest(sink=sink, field=field):
                    self.assertTrue(settings[f"field_map_{field}"])
                    self.assertEqual("locked", settings[f"field_lock_{field}"])
                    self.assertEqual(update, settings[f"field_updatelocal_{field}"])

    def test_the_mappings_render_from_the_claims_and_the_attributes(self):
        oidc = _sink("MOODLE_OIDC_SETTINGS")
        ldap = _sink("MOODLE_LDAP_SETTINGS")
        self.assertEqual(OIDC["ATTRIBUTES"]["GIVEN_NAME"], oidc["field_map_firstname"])
        self.assertEqual(OIDC["ATTRIBUTES"]["USERNAME"], oidc["bindingusernameclaim"])
        self.assertEqual(OIDC["CLIENT"]["TOKEN_URL"], oidc["tokenendpoint"])
        self.assertEqual("street", oidc["field_map_address"])
        self.assertEqual(
            LDAP["USER"]["ATTRIBUTES"]["PHONETIC_FAMILY"],
            ldap["field_map_lastnamephonetic"],
        )
        self.assertEqual(LDAP["DN"]["ADMINISTRATOR"]["DATA"], ldap["bind_dn"])

    def test_the_role_contexts_name_the_rbac_groups_of_the_role(self):
        ldap = _sink("MOODLE_LDAP_SETTINGS")
        self.assertEqual(
            f"cn=web-app-moodle-manager,{ROLES_OU}", ldap["managercontext"]
        )
        self.assertEqual(
            f"cn=web-app-moodle-coursecreator,{ROLES_OU}", ldap["coursecreatorcontext"]
        )

    def test_ldap_creates_accounts_only_without_sso(self):
        self.assertEqual(0, _sink("MOODLE_LDAP_SETTINGS", sso=True)["auth_user_create"])
        self.assertEqual(
            1, _sink("MOODLE_LDAP_SETTINGS", sso=False)["auth_user_create"]
        )


class TestCallers(unittest.TestCase):
    def test_each_caller_hands_its_form_its_sink_and_only_its_credentials(self):
        for tasks_file, form, sink, hidden in CASES:
            with self.subTest(tasks=tasks_file):
                task = _task(tasks_file, f"Converge the {form}")
                self.assertEqual("utils/plugin/form.yml", task["include_tasks"])
                self.assertEqual(form, task["vars"]["moodle_plugin_form_component"])
                self.assertEqual(
                    f"{{{{ {sink} }}}}", task["vars"]["moodle_plugin_form_settings"]
                )
                rendered = _render(task["vars"]["moodle_plugin_form_hidden"])
                self.assertEqual(hidden, set(rendered))
                self.assertFalse(hidden & set(_forms()[form]["fields"]))

    def test_removecontexts_is_written_only_while_oidc_is_the_login(self):
        for enabled, expected in (
            (True, {"bind_pw", "removecontexts"}),
            (False, {"bind_pw"}),
        ):
            with self.subTest(oidc=enabled):
                task = _task("06_ldap_sync.yml", "Converge the auth_ldap")
                self.assertEqual(
                    expected,
                    set(
                        _render(task["vars"]["moodle_plugin_form_hidden"], sso=enabled)
                    ),
                )

    def test_no_setting_is_written_beside_the_applier_anymore(self):
        for tasks_file, _form, _sink_name, _hidden in CASES:
            with self.subTest(tasks=tasks_file):
                self.assertNotIn(
                    "cfg.php", json.dumps(_tasks(tasks_file), ensure_ascii=False)
                )

    def test_the_mfa_util_writes_without_hidden_settings(self):
        task = _task("utils/plugin/config.yml", "Apply the")
        self.assertIn("'mode': 'write'", task["args"]["stdin"])
        self.assertIn("'hidden': {}", task["args"]["stdin"])


class TestForcedSettings(unittest.TestCase):
    def test_moodle_forces_each_plugin_with_its_form_and_unlisted_settings(self):
        forced = _sink("MOODLE_FORCED_PLUGIN_SETTINGS")
        for _tasks_file, form, sink, hidden in CASES:
            with self.subTest(form=form):
                unlisted = _sink(sink.replace("_SETTINGS", "_UNLISTED_SETTINGS"))
                self.assertEqual({**_sink(sink), **unlisted}, dict(forced[form]))
                self.assertEqual(
                    hidden - CREDENTIALS[form], set(forced[form]) - set(_sink(sink))
                )

    def test_no_credential_reaches_the_environment(self):
        forced = _sink("MOODLE_FORCED_PLUGIN_SETTINGS")
        encoded = _render("{{ MOODLE_FORCED_PLUGIN_SETTINGS | to_json | b64encode }}")
        decoded = base64.b64decode(encoded).decode()
        for form, names in CREDENTIALS.items():
            with self.subTest(form=form):
                self.assertFalse(names & set(forced[form]))
        for secret in (OIDC["CLIENT"]["SECRET"], LDAP["BIND_CREDENTIAL"]):
            self.assertNotIn(secret, decoded)

    def test_the_credentials_stay_converged_by_the_applier_unforced(self):
        for tasks_file, form, _sink_name, _hidden in CASES:
            with self.subTest(form=form):
                task = _task(tasks_file, f"Converge the {form}")
                self.assertTrue(
                    CREDENTIALS[form]
                    <= set(_render(task["vars"]["moodle_plugin_form_hidden"]))
                )

    def test_a_plugin_is_forced_only_while_its_service_is_on(self):
        self.assertEqual(
            ["auth_ldap"], list(_sink("MOODLE_FORCED_PLUGIN_SETTINGS", sso=False))
        )
        self.assertEqual(
            ["auth_oidc"], list(_sink("MOODLE_FORCED_PLUGIN_SETTINGS", ldap=False))
        )
        self.assertEqual(
            {}, _sink("MOODLE_FORCED_PLUGIN_SETTINGS", ldap=False, sso=False)
        )

    def test_the_env_hands_the_forced_settings_to_config_php_as_base64_json(self):
        self.assertIn(
            "MOODLE_FORCED_PLUGIN_SETTINGS={{ MOODLE_FORCED_PLUGIN_SETTINGS | to_json | b64encode }}\n",
            read_text(str(ROLE / "templates/env.j2")),
        )

    def test_config_php_forces_them_before_moodle_boots_and_keeps_objectfs(self):
        config = read_text(str(ROLE / "files/build/config.php"))
        merge = config.index("$CFG->forced_plugin_settings = array_replace(")
        self.assertLess(config.index("'tool_objectfs' => array("), merge)
        self.assertLess(
            merge, config.index("require_once(__DIR__ . '/lib/setup.php');")
        )
        self.assertIn("moodle_env('MOODLE_FORCED_PLUGIN_SETTINGS')", config[merge:])
        self.assertIn("array_map('strval', $settings)", config[merge:])

    def test_both_forms_rely_on_the_native_lock_alone(self):
        for _tasks_file, form, _sink_name, _hidden in CASES:
            with self.subTest(form=form):
                self.assertIs(True, _forms()[form]["native"])
        self.assertFalse((ROLE / "templates/javascript.js.j2").exists())
        services = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
        self.assertNotIn("javascript", services)


class TestPluginForm(unittest.TestCase):
    UTIL = "utils/plugin/form.yml"

    def test_the_drift_report_runs_between_the_read_and_the_write(self):
        self.assertLess(
            _position(self.UTIL, "Read the stored"), _position(self.UTIL, "Report the")
        )
        self.assertLess(
            _position(self.UTIL, "Report the"), _position(self.UTIL, "Write the")
        )

    def test_the_read_and_the_write_hand_the_applier_the_same_payload(self):
        read = _task(self.UTIL, "Read the stored")
        write = _task(self.UTIL, "Write the")
        self.assertEqual(read["ansible.builtin.shell"], write["ansible.builtin.shell"])
        self.assertEqual(
            read["args"]["stdin"].replace("'mode': 'read'", "'mode': 'write'"),
            write["args"]["stdin"],
        )
        self.assertIn("'mode': 'read'", read["args"]["stdin"])
        self.assertIs(False, read["changed_when"])

    def test_the_drift_report_names_the_form_of_the_component(self):
        task = _task(self.UTIL, "Report the")
        self.assertEqual(DRIFT, task["include_tasks"])
        current = _templated(
            _trust_as_template(task["vars"]["forms_drift_current"]),
            {
                "moodle_plugin_form_component": "auth_ldap",
                **_stored({"host_url": "ldap://old"}, 1, "Notice: deprecated\n"),
            },
            {},
        )
        self.assertEqual({"auth_ldap": {"host_url": "ldap://old"}}, current)

    def test_the_write_runs_only_while_a_setting_or_a_hidden_setting_differs(self):
        when = _task(self.UTIL, "Write the")["when"]
        for stored, runs in (
            (_stored({}, 0), False),
            (_stored({}, 0, "Deprecated: noise\n"), False),
            (_stored({"host_url": None}, 0), True),
            (_stored({}, 1), True),
        ):
            with self.subTest(stored=stored):
                self.assertIs(
                    runs,
                    _templated(
                        _trust_as_template("{{ (" + when + ") | bool }}"), stored, {}
                    ),
                )

    def test_every_applier_run_keeps_the_payload_out_of_the_log(self):
        for fragment in ("Read the stored", "Write the"):
            with self.subTest(task=fragment):
                self.assertEqual(
                    "{{ MASK_CREDENTIALS_IN_LOGS | bool }}",
                    _task(self.UTIL, fragment)["no_log"],
                )


if __name__ == "__main__":
    unittest.main()
