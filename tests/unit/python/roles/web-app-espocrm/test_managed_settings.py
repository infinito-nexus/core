from __future__ import annotations

import base64
import json
import re
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

ROLE = PROJECT_ROOT / "roles/web-app-espocrm"
ORIG_ENV_AUTHENTICATION = (
    "{{ 'Oidc' if ESPOCRM_LOGIN_SSO | bool else "
    "('LDAP' if ESPOCRM_LOGIN_LDAP | bool else 'Espo') }}"
)
DRIFT = "{{ lookup('path_absolute', 'tasks/utils/forms/drift.yml') }}"
SETTINGS = {
    "authentication_method": "authenticationMethod",
    "auth2_f_a": "auth2FA",
    "auth2_f_a_forced": "auth2FAForced",
    "oidc_fallback": "oidcFallback",
    "maintenance_mode": "maintenanceMode",
    "cron_disabled": "cronDisabled",
    "use_cache": "useCache",
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
    return load_yaml_any(str(ROLE / "tasks/02_manager_ops.yml"), default_if_missing=[])


def _task(fragment: str) -> dict:
    return next(task for task in _tasks() if fragment in task["name"])


def _position(fragment: str) -> int:
    return next(i for i, task in enumerate(_tasks()) if fragment in task["name"])


def _sinks(
    sso=True,
    ldap=False,
    native=False,
    maintenance=False,
    second_factor=False,
    enforced=True,
) -> dict:
    login = {
        "services.espocrm.login.method.sso.enabled": sso,
        "services.espocrm.login.method.ldap.enabled": ldap,
        "services.espocrm.login.method.2fa.enabled": second_factor,
        "services.espocrm.login.method.2fa.enforced": enforced,
    }
    declared = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
    )
    stubs = {"config": lambda _app, path: login[path]}
    application = {
        "services": {
            "sso": {"enabled": sso},
            "espocrm": {
                "authentication_method": _templated(
                    declared["espocrm"]["authentication_method"], {}, stubs
                ),
                "second_factor_forced": _templated(
                    declared["espocrm"]["second_factor_forced"], {}, stubs
                ),
                "login": {
                    "method": {
                        "native": {"enabled": native},
                        "2fa": {"enabled": second_factor, "enforced": enforced},
                    }
                },
                "maintenance_mode": maintenance,
            },
        }
    }
    variables = {
        **DataLoader().load_from_file(
            str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
        ),
        "application_id": "web-app-espocrm",
    }
    stubs = {"form_values": lambda _app, form: values(form, _forms(), application, {})}
    return {
        sink: dict(_templated(variables[sink], variables, stubs))
        for sink in (
            "ESPOCRM_AUTHENTICATION_SETTINGS",
            "ESPOCRM_SYSTEM_SETTINGS",
            "ESPOCRM_FORM_SETTINGS",
        )
    }


def _env_lines(settings: dict) -> list[str]:
    text = read_text(str(ROLE / "templates/env.j2"))
    block = re.search(
        r"^\{% for espocrm_field.*?^\{% endfor %\}\n", text, re.MULTILINE | re.DOTALL
    ).group(0)
    rendered = _templated(
        _trust_as_template(block), {"ESPOCRM_FORM_SETTINGS": settings}, {}
    )
    return [line for line in rendered.splitlines() if line]


def _locked(settings: dict) -> dict:
    payload = _templated(
        _trust_as_template(read_text(str(ROLE / "templates/forms_module_payload.j2"))),
        {"ESPOCRM_FORM_SETTINGS": settings},
        {},
    )
    files = dict(line.split(" ", 1) for line in payload.splitlines() if line)
    return {path: json.loads(base64.b64decode(data)) for path, data in files.items()}


def _stored(settings: dict, hidden: int, noise: str = "") -> dict:
    report = json.dumps({"settings": settings, "hidden": hidden})
    return {"espocrm_settings_stored": {"stdout_lines": [*noise.splitlines(), report]}}


class TestSink(unittest.TestCase):
    def test_the_authentication_method_matches_the_old_login_mapping(self):
        for sso, ldap in ((True, True), (True, False), (False, True), (False, False)):
            with self.subTest(sso=sso, ldap=ldap):
                old = _templated(
                    _trust_as_template(ORIG_ENV_AUTHENTICATION),
                    {"ESPOCRM_LOGIN_SSO": sso, "ESPOCRM_LOGIN_LDAP": ldap},
                    {},
                )
                self.assertEqual(
                    old,
                    _sinks(sso=sso, ldap=ldap)["ESPOCRM_AUTHENTICATION_SETTINGS"][
                        "authentication_method"
                    ],
                )

    def test_the_oidc_fallback_follows_the_native_login_only_under_sso(self):
        for native in (True, False):
            with self.subTest(native=native):
                self.assertIs(
                    native,
                    _sinks(native=native)["ESPOCRM_AUTHENTICATION_SETTINGS"][
                        "oidc_fallback"
                    ],
                )
        self.assertNotIn(
            "oidc_fallback", _sinks(sso=False)["ESPOCRM_AUTHENTICATION_SETTINGS"]
        )

    def test_the_second_factor_is_forced_only_while_it_is_on_and_enforced(self):
        for second_factor in (True, False):
            for enforced in (True, False):
                with self.subTest(second_factor=second_factor, enforced=enforced):
                    sink = _sinks(second_factor=second_factor, enforced=enforced)
                    self.assertEqual(
                        (second_factor, second_factor and enforced),
                        (
                            sink["ESPOCRM_AUTHENTICATION_SETTINGS"]["auth2_f_a"],
                            sink["ESPOCRM_AUTHENTICATION_SETTINGS"]["auth2_f_a_forced"],
                        ),
                    )

    def test_maintenance_disables_cron_and_cache_together(self):
        for maintenance in (True, False):
            with self.subTest(maintenance=maintenance):
                self.assertEqual(
                    {
                        "maintenance_mode": maintenance,
                        "cron_disabled": maintenance,
                        "use_cache": not maintenance,
                    },
                    _sinks(maintenance=maintenance)["ESPOCRM_SYSTEM_SETTINGS"],
                )

    def test_each_sink_reads_only_its_own_form(self):
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        for form, block in _forms().items():
            with self.subTest(form=form):
                self.assertEqual(
                    f"{{{{ lookup('form_values', application_id, '{form}') }}}}",
                    variables[block["sinks"][0]],
                )


class TestEnvironment(unittest.TestCase):
    def test_every_setting_reaches_the_seeder_under_its_old_name_and_value(self):
        settings = _sinks()["ESPOCRM_FORM_SETTINGS"]
        self.assertEqual(
            [
                "ESPOCRM_SEED_AUTHENTICATION_METHOD=Oidc",
                "ESPOCRM_SEED_AUTH2_F_A=false",
                "ESPOCRM_SEED_AUTH2_F_A_FORCED=false",
                "ESPOCRM_SEED_OIDC_FALLBACK=false",
                "ESPOCRM_SEED_MAINTENANCE_MODE=false",
                "ESPOCRM_SEED_CRON_DISABLED=false",
                "ESPOCRM_SEED_USE_CACHE=true",
            ],
            _env_lines(settings),
        )

    def test_no_setting_is_rendered_beside_the_sink(self):
        text = read_text(str(ROLE / "templates/env.j2"))
        for field in SETTINGS:
            with self.subTest(field=field):
                self.assertNotIn(f"ESPOCRM_SEED_{field.upper()}=", text)

    def test_the_seed_name_becomes_the_setting_the_form_shows(self):
        fields = {
            field: spec
            for block in _forms().values()
            for field, spec in block["fields"].items()
        }
        self.assertEqual(set(SETTINGS), set(fields))
        for field, setting in SETTINGS.items():
            with self.subTest(field=field):
                first, *rest = field.split("_")
                self.assertEqual(setting, first + "".join(p.capitalize() for p in rest))
                self.assertEqual(
                    f'.field[data-name="{setting}"]', fields[field]["selector"]
                )


class TestLock(unittest.TestCase):
    def test_every_managed_setting_is_read_only(self):
        locked = _locked(_sinks()["ESPOCRM_FORM_SETTINGS"])
        self.assertEqual({"order": 100}, locked["Resources/module.json"])
        self.assertEqual(
            {"fields": {setting: {"readOnly": True} for setting in SETTINGS.values()}},
            locked["Resources/metadata/entityDefs/Settings.json"],
        )

    def test_only_the_settings_the_sink_carries_are_locked(self):
        locked = _locked(_sinks(sso=False)["ESPOCRM_FORM_SETTINGS"])
        self.assertNotIn(
            "oidcFallback",
            locked["Resources/metadata/entityDefs/Settings.json"]["fields"],
        )

    def test_every_form_is_native_and_no_javascript_is_injected(self):
        for form, block in _forms().items():
            with self.subTest(form=form):
                self.assertIs(True, block.get("native"))
        services = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
        self.assertNotIn("javascript", services)

    def test_the_lock_module_replaces_its_own_directory(self):
        task = _task("Lock the managed EspoCRM settings")
        self.assertIn("ESPOCRM_FORMS_MODULE_PATH", task["ansible.builtin.shell"]["cmd"])
        self.assertIn("forms_module_payload.j2", task["ansible.builtin.shell"]["stdin"])
        self.assertEqual(
            "custom/Espo/Modules/InfinitoForms",
            load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))["ESPOCRM_FORMS_MODULE_PATH"],
        )


class TestConverge(unittest.TestCase):
    def test_the_drift_report_runs_between_the_read_and_the_write(self):
        self.assertLess(_position("Read the stored"), _position("Report the managed"))
        self.assertLess(_position("Report the managed"), _position("Write the EspoCRM"))
        self.assertLess(_position("Write the EspoCRM"), _position("Lock the managed"))

    def test_the_read_compares_only_and_names_the_form_fields(self):
        read = _task("Read the stored")
        self.assertIn("-e ESPOCRM_SEEDER_MODE=read", read["shell"])
        self.assertIn("ESPOCRM_FORM_SETTINGS | join(',') | quote", read["shell"])
        self.assertNotIn("ESPOCRM_SEEDER_MODE", _task("Write the EspoCRM")["shell"])
        self.assertIs(False, read["changed_when"])
        self.assertIn("MASK_CREDENTIALS_IN_LOGS", read["no_log"])

    def test_the_read_never_runs_as_root(self):
        read = _task("Read the stored")["shell"]
        self.assertEqual(
            ["{{ ESPOCRM_USER }}"],
            re.findall(r"(?:--user[ =]|-u )(\{\{[^}]*\}\}|\S+)", read),
        )
        user = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})[
            "ESPOCRM_USER"
        ]
        self.assertNotIn(str(user).strip(), {"root", "0", "0:0", "root:root", ""})

    def test_the_drift_report_splits_the_read_by_form(self):
        task = _task("Report the managed")
        self.assertEqual(DRIFT, task["include_tasks"])
        sinks = _sinks()
        variables = {
            **_stored(
                {"authentication_method": "Espo", "use_cache": False},
                2,
                "Deprecated: noise\n",
            ),
            **sinks,
            "espocrm_settings_drift": _trust_as_template(
                task["vars"]["espocrm_settings_drift"]
            ),
        }
        self.assertEqual(
            {
                "authentication": {"authentication_method": "Espo"},
                "system": {"use_cache": False},
            },
            {
                form: _templated(_trust_as_template(node), variables, {})
                for form, node in task["vars"]["forms_drift_current"].items()
            },
        )

    def test_the_write_runs_only_while_a_setting_differs(self):
        when = _task("Write the EspoCRM")["when"]
        for stored, runs in (
            (_stored({}, 0), False),
            (_stored({}, 0, "Deprecated: noise\n"), False),
            (_stored({"maintenance_mode": True}, 0), True),
            (_stored({}, 1), True),
        ):
            with self.subTest(stored=stored):
                self.assertIs(
                    runs,
                    _templated(
                        _trust_as_template("{{ (" + when + ") | bool }}"), stored, {}
                    ),
                )

    def test_the_read_mode_returns_before_the_seeder_writes(self):
        seeder = read_text(str(ROLE / "files/php/seed/config.php"))
        loop = seeder.index("foreach ($_ENV as $envKey => $envValue)")
        read_branch = seeder.index("if ($readOnly) {", loop)
        self.assertLess(read_branch, seeder.index("$writer->set(", loop))
        self.assertIn("continue;\n    }\n\n    if ($current !== $value) {", seeder)
        report = seeder.index("if ($readOnly) {", read_branch + 1)
        self.assertLess(report, seeder.index("$writer->save();"))
        self.assertIn("exit(0);", seeder[report : seeder.index("$writer->save();")])


if __name__ == "__main__":
    unittest.main()
