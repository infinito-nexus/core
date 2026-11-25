from __future__ import annotations

import json
import unittest
import unittest.mock as mock

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

ROLE = PROJECT_ROOT / "roles/web-app-matomo"
TASKS = "addons/rebeloidc.yml"
DRIFT = "{{ lookup('path_absolute', 'tasks/utils/forms/drift.yml') }}"
HTTPS_ISSUER = "https://auth.example.test/realms/example"
HTTP_ISSUERS = (
    "http://auth." + "a" * 56 + ".onion/realms/example",
    "http://auth.example.test/realms/example",
)
OIDC = {
    "BUTTON_TEXT": "Sign in with Keycloak",
    "CLIENT": {
        "ISSUER_URL": HTTPS_ISSUER,
        "AUTHORIZE_URL": "https://auth.example.test/authorize",
        "TOKEN_URL": "https://auth.example.test/token",
        "USER_INFO_URL": "https://auth.example.test/userinfo",
        "LOGOUT_URL": "https://auth.example.test/logout",
        "ID": "matomo",
        "SECRET": "oidc-client-secret",
    },
    "ATTRIBUTES": {"USERNAME": "preferred_username"},
}
RBAC = {"GROUP": {"CLAIM": "groups"}}
OLD_SETTINGS = {
    "authenticationName": "Sign in with Keycloak",
    "authorizeUrl": "https://auth.example.test/authorize",
    "tokenUrl": "https://auth.example.test/token",
    "userInfoUrl": "https://auth.example.test/userinfo",
    "endSessionUrl": "https://auth.example.test/logout",
    "userInfoId": "preferred_username",
    "usernameAttribute": "preferred_username",
    "fallbackToEmail": False,
    "clientId": "matomo",
    "clientSecret": "oidc-client-secret",
    "scope": "openid profile email groups",
    "allowSignup": False,
    "autoLinking": True,
    "disableSuperuser": False,
    "disablePasswordConfirmation": True,
    "fineGrainedPermissions": False,
}


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


def _templated(node, variables: dict, stubs: dict):
    real_get = lookup_loader.get

    def get(lookup_name, *args, **kwargs):
        if lookup_name in stubs:
            return _Stub(stubs[lookup_name])
        return real_get(lookup_name, *args, **kwargs)

    templar = Templar(loader=DataLoader(), variables=variables)
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(node)


def _forms() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})


def _tasks() -> list[dict]:
    return load_yaml_any(str(ROLE / "tasks" / TASKS), default_if_missing=[])


def _task(fragment: str) -> dict:
    return next(task for task in _tasks() if fragment in task["name"])


def _position(fragment: str) -> int:
    return next(i for i, task in enumerate(_tasks()) if fragment in task["name"])


def _variables(sso: bool = True, issuer: str = HTTPS_ISSUER) -> dict:
    """
    Args:
        sso: whether the RebelOIDC sign-in is on.
        issuer: the OIDC issuer URL of the deployment.

    Returns:
        The variables vars/main.yml renders against, with the ``_stubs`` lookups.
    """
    oidc = {**OIDC, "CLIENT": {**OIDC["CLIENT"], "ISSUER_URL": issuer}}
    declared = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
    )
    application = {
        "services": {
            "sso": {"enabled": sso},
            "matomo": {
                "oidc": _templated(
                    declared["matomo"]["oidc"], {"OIDC": oidc, "RBAC": RBAC}, {}
                )
            },
        }
    }
    variables = {
        **DataLoader().load_from_file(
            str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
        ),
        "application_id": "web-app-matomo",
        "OIDC": oidc,
        "RBAC": RBAC,
    }
    variables["MATOMO_OIDC_ENABLED"] = sso
    variables["MATOMO_OIDC_PLUGIN"] = "RebelOIDC"
    variables["MATOMO_RBAC_LOGIN_SETTINGS"] = {"groups_claim": "groups"}
    variables["_stubs"] = {
        "form_values": lambda _app, form: values(form, _forms(), application, {})
    }
    return variables


def _render(name: str, sso: bool = True, issuer: str = HTTPS_ISSUER):
    variables = _variables(sso, issuer)
    stubs = variables.pop("_stubs")
    return _templated(variables[name], variables, stubs)


def _stored(settings: dict, hidden: int, noise: str = "") -> dict:
    report = json.dumps({"settings": settings, "hidden": hidden})
    return {
        "matomo_oidc_stored": {"stdout_lines": [*noise.splitlines(), report]},
        "MATOMO_OIDC_PLUGIN": "RebelOIDC",
    }


class TestSink(unittest.TestCase):
    def test_the_converged_section_equals_the_old_settings(self):
        self.assertEqual(
            OLD_SETTINGS, dict(_render("MATOMO_CONFIG_SECTIONS")["RebelOIDC"])
        )

    def test_the_rbac_section_is_kept(self):
        self.assertEqual(
            {"groups_claim": "groups"},
            dict(_render("MATOMO_CONFIG_SECTIONS")["InfinitoRbacLogin"]),
        )

    def test_both_sections_are_emptied_while_sso_is_off(self):
        self.assertEqual(
            {"RebelOIDC": {}, "InfinitoRbacLogin": {}},
            _render("MATOMO_CONFIG_SECTIONS", sso=False),
        )
        self.assertEqual({}, dict(_render("MATOMO_OIDC_SETTINGS", sso=False)))

    def test_the_client_secret_stays_out_of_the_form_and_the_sink(self):
        sink = _render("MATOMO_OIDC_SETTINGS")
        self.assertNotIn("clientSecret", sink)
        self.assertNotIn(OIDC["CLIENT"]["SECRET"], json.dumps(dict(sink)))
        self.assertNotIn("clientSecret", _forms()["rebeloidc"]["fields"])

    def test_the_form_fields_are_the_plugin_settings(self):
        self.assertEqual(
            [key for key in OLD_SETTINGS if key != "clientSecret"],
            list(_forms()["rebeloidc"]["fields"]),
        )


class TestTransport(unittest.TestCase):
    def test_an_http_issuer_lets_rebeloidc_call_it(self):
        for issuer in HTTP_ISSUERS:
            with self.subTest(issuer=issuer):
                sections = _render("MATOMO_CONFIG_SECTIONS", issuer=issuer)
                self.assertEqual(
                    {**OLD_SETTINGS, "allow_http": True},
                    dict(sections["RebelOIDC"]),
                    "RebelOIDC's Protocol::checkSecureUrl throws on every non-https "
                    "provider URL unless [RebelOIDC] allow_http is set, and the "
                    "converge rewrites that section to exactly these keys",
                )

    def test_an_https_issuer_keeps_rebeloidc_on_https(self):
        sections = _render("MATOMO_CONFIG_SECTIONS", issuer=HTTPS_ISSUER)
        self.assertNotIn("allow_http", dict(sections["RebelOIDC"]))


class TestLock(unittest.TestCase):
    def test_the_form_is_native(self):
        self.assertIs(True, _forms()["rebeloidc"]["native"])

    def test_every_field_names_its_setting(self):
        for field, spec in _forms()["rebeloidc"]["fields"].items():
            with self.subTest(field=field):
                self.assertEqual(f'[name="{field}"]', spec["selector"])


class TestConverge(unittest.TestCase):
    def test_the_drift_report_runs_between_the_read_and_the_write(self):
        self.assertLess(_position("Read the stored"), _position("Report the managed"))
        self.assertLess(
            _position("Report the managed"), _position("Converge the sign-in")
        )

    def test_the_read_and_the_write_hand_the_script_the_same_sections(self):
        read = _task("Read the stored")
        write = _task("Converge the sign-in")
        self.assertEqual(
            read["ansible.builtin.shell"]["stdin"],
            write["ansible.builtin.shell"]["stdin"],
        )
        self.assertEqual(
            read["ansible.builtin.shell"]["cmd"].replace(
                " -e MATOMO_CONFIG_MODE=read -e MATOMO_CONFIG_FORM_FIELDS", ""
            ),
            write["ansible.builtin.shell"]["cmd"],
        )
        self.assertIs(False, read["changed_when"])
        self.assertEqual(read["no_log"], write["no_log"])

    def test_the_read_names_only_the_form_fields(self):
        node = _task("Read the stored")["environment"]["MATOMO_CONFIG_FORM_FIELDS"]
        variables = _variables()
        stubs = variables.pop("_stubs")
        self.assertEqual(
            {"RebelOIDC": [k for k in OLD_SETTINGS if k != "clientSecret"]},
            json.loads(_templated(_trust_as_template(node), variables, stubs)),
        )

    def test_the_drift_report_names_the_form(self):
        task = _task("Report the managed")
        self.assertEqual(DRIFT, task["include_tasks"])
        node = task["vars"]["forms_drift_current"]["rebeloidc"]
        for stored, expected in (
            (
                _stored({"RebelOIDC": {"scope": "openid"}}, 1, "Notice\n"),
                {"scope": "openid"},
            ),
            (_stored({}, 2), {}),
        ):
            with self.subTest(stored=stored):
                self.assertEqual(
                    expected, _templated(_trust_as_template(node), stored, {})
                )

    def test_the_write_runs_only_while_something_differs(self):
        when = _task("Converge the sign-in")["when"]
        for stored, runs in (
            (_stored({}, 0), False),
            (_stored({}, 0, "Notice\n"), False),
            (_stored({"RebelOIDC": {"scope": "openid"}}, 0), True),
            (_stored({}, 1), True),
        ):
            with self.subTest(stored=stored):
                self.assertIs(
                    runs,
                    _templated(
                        _trust_as_template("{{ (" + when + ") | bool }}"), stored, {}
                    ),
                )

    def test_the_script_reads_without_writing(self):
        script = read_text(str(ROLE / "files/php/config_converge.php"))
        report = script.index("if ($readOnly) {\n    $hidden")
        self.assertLess(report, script.index("$config->forceSave();"))
        self.assertIn(
            "exit(0);", script[report : script.index("$config->forceSave();")]
        )
        loop = script.index("foreach ($sections as $section => $settings)")
        self.assertLess(
            script.index(
                "        continue;\n    }\n    if ($stored != $desired)", loop
            ),
            script.index("$config->$section = $desired;", loop),
        )


if __name__ == "__main__":
    unittest.main()
