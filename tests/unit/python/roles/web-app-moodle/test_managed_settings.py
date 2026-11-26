from __future__ import annotations

import base64
import json
import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar
from jinja2 import Environment, StrictUndefined, select_autoescape

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
KEYCLOAK_MOODLE_SCOPE = (
    PROJECT_ROOT / "roles/web-app-keycloak/templates/import/scopes/moodle.json.j2"
)
AUTH_OIDC_TOKEN_FIELDS = frozenset(
    {
        "bindingusernameclaim",
        "objectId",
        "userPrincipalName",
        "givenName",
        "surname",
        "mail",
    }
)
AUTH_OIDC_UPDATE_EVENTS = {
    "always": {"create", "login", "usersync"},
    "oncreate": {"create"},
    "onlogin": {"login", "usersync"},
    "oncreate_usersync": {"create", "usersync"},
}
AUTH_OIDC_RESERVED_CLAIMS = frozenset(
    {
        *("iss", "sub", "aud", "exp", "nbf", "iat", "jti", "name", "given_name"),
        *("family_name", "middle_name", "nickname", "preferred_username", "profile"),
        *("picture", "website", "email", "email_verified", "gender", "birthdate"),
        *("zoneinfo", "locale", "phone_number", "phone_number_verified", "address"),
        *("updated_at", "auth_time", "nonce", "acr", "amr", "azp", "at_hash", "c_hash"),
        *("sid", "aio", "acrs", "altsecid", "appid", "appidacr", "azpacr", "ctry"),
        *("fwd", "group", "idp", "idtyp", "in_corp", "ipaddr", "login_hint", "oid"),
        *("onprem_sid", "platf", "puid", "pwd_exp", "pwd_url", "rh", "scp"),
        *("tenant_ctry", "tid", "unique_name", "upn", "uti", "ver"),
        *("verified_primary_email", "verified_secondary_email", "vnet", "wids"),
        *("xms_cc", "xms_edov", "xms_pdl", "xms_pl", "xms_tpl", "typ", "session_state"),
        *("allowed-origins", "realm_access", "resource_access", "scope"),
        *("samaccountname", "bindingusernameclaim", "objectid", "userprincipalname"),
        *("displayname", "givenname", "surname", "mail", "onpremisessamaccountname"),
        *("streetaddress", "city", "postalcode", "state", "country", "jobtitle"),
        *("department", "companyname", "preferredlanguage", "employeeid"),
        *("businessphones", "faxnumber", "mobilephone", "officelocation"),
        *("preferredname", "manager", "manager_email", "teams", "sds_school_id"),
        *("sds_school_name", "sds_school_role", "sds_student_externalid"),
        *("sds_student_birthdate", "sds_student_grade", "sds_student_graduationyear"),
        *("sds_student_studentnumber", "sds_teacher_externalid"),
        *("sds_teacher_teachernumber",),
        *(f"extensionattribute{index}" for index in range(1, 16)),
    }
)
CASES = (
    (
        "04_oidc.yml",
        "auth_oidc",
        "MOODLE_OIDC_SETTINGS",
        {"clientsecret", "oidcscope", "customclaims"},
    ),
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
            ("MOODLE_OIDC_SETTINGS", "always"),
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
        self.assertIn(oidc["field_map_firstname"], AUTH_OIDC_TOKEN_FIELDS)
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


def _scope_claims() -> dict:
    rendered = _templated(
        _trust_as_template(read_text(str(KEYCLOAK_MOODLE_SCOPE))),
        {"application_id": "web-app-keycloak"},
        {"config": lambda _app, _key: "moodle"},
    )
    scope = rendered if isinstance(rendered, dict) else json.loads(rendered)
    return {
        mapper["config"]["claim.name"]: mapper["config"]["user.attribute"]
        for mapper in scope["protocolMappers"]
    }


def _oidc_field_maps() -> dict:
    return {
        key.removeprefix("field_map_"): value
        for key, value in _sink("MOODLE_OIDC_SETTINGS").items()
        if key.startswith("field_map_")
    }


def _plugin_fills(remote: str, custom_claims: set, scope_claims: dict) -> bool:
    """
    Args:
        remote: the field_map value of a Moodle profile field.
        custom_claims: the claim names of the ``customclaims`` setting.
        scope_claims: claim name to Keycloak user attribute of the moodle client scope.

    Returns:
        True when the plugin fills ``remote`` from the token on its own, or reads it as a
        configured custom claim that is not reserved and that the moodle scope emits.
    """
    if remote in AUTH_OIDC_TOKEN_FIELDS:
        return True
    return (
        remote in custom_claims
        and remote.lower() not in AUTH_OIDC_RESERVED_CLAIMS
        and remote in scope_claims
    )


def _refreshes_on_login(update: str) -> bool:
    return {"create", "login"} <= AUTH_OIDC_UPDATE_EVENTS.get(update, set())


class TestOidcClaimMapping(unittest.TestCase):
    def test_every_field_is_written_at_creation_and_refreshed_on_every_login(self):
        settings = _sink("MOODLE_OIDC_SETTINGS")
        for field in PROFILE_FIELDS:
            with self.subTest(field=field):
                self.assertTrue(
                    _refreshes_on_login(settings[f"field_updatelocal_{field}"])
                )

    def test_an_update_value_the_plugin_does_not_know_refreshes_nothing(self):
        for update in ("oneveryloginupdate", "oncreate", "onlogin"):
            with self.subTest(update=update):
                self.assertFalse(_refreshes_on_login(update))

    def test_every_mapped_field_reads_a_value_the_plugin_fills(self):
        custom = set(_sink("MOODLE_OIDC_UNLISTED_SETTINGS")["customclaims"].split())
        scope = _scope_claims()
        for field, remote in _oidc_field_maps().items():
            with self.subTest(field=field, remote=remote):
                self.assertTrue(_plugin_fills(remote, custom, scope))

    def test_a_standard_or_plugin_claim_name_is_never_filled_even_when_listed(self):
        for remote in ("given_name", "middle_name", "country", "department", "address"):
            with self.subTest(remote=remote):
                self.assertFalse(_plugin_fills(remote, {remote}, {remote: "attribute"}))

    def test_customclaims_lists_exactly_the_claims_the_fields_read_beside_the_token_fields(
        self,
    ):
        custom = _sink("MOODLE_OIDC_UNLISTED_SETTINGS")["customclaims"].split()
        self.assertEqual(len(custom), len(set(custom)))
        self.assertEqual(
            set(_oidc_field_maps().values()) - AUTH_OIDC_TOKEN_FIELDS, set(custom)
        )

    def test_customclaims_is_empty_while_sso_is_off(self):
        self.assertEqual(
            "", _sink("MOODLE_OIDC_UNLISTED_SETTINGS", sso=False)["customclaims"]
        )

    def test_the_scope_feeds_middle_name_address_country_and_department_from_their_user_attributes(
        self,
    ):
        scope = _scope_claims()
        maps = _oidc_field_maps()
        for field, attribute in (
            ("middlename", "middleName"),
            ("address", "street"),
            ("country", "country"),
            ("department", "department"),
        ):
            with self.subTest(field=field):
                self.assertEqual(attribute, scope[maps[field]])


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
        environment = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        environment.filters["to_json"] = json.dumps
        payload = environment.from_string(task["args"]["stdin"]).render(
            moodle_plugin_config_component="tool_mfa",
            moodle_plugin_config_settings={"enabled": "1"},
        )
        self.assertEqual(
            {
                "component": "tool_mfa",
                "mode": "write",
                "settings": {"enabled": "1"},
                "hidden": {},
            },
            json.loads(payload),
        )


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
                self.assertLessEqual(
                    CREDENTIALS[form],
                    set(_render(task["vars"]["moodle_plugin_form_hidden"])),
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
        line = next(
            row
            for row in read_text(str(ROLE / "templates/env.j2")).splitlines()
            if row.startswith("MOODLE_FORCED_PLUGIN_SETTINGS=")
        )
        encoded = _render(line).split("=", 1)[1]
        self.assertEqual(
            _sink("MOODLE_FORCED_PLUGIN_SETTINGS"),
            json.loads(base64.b64decode(encoded)),
        )

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
