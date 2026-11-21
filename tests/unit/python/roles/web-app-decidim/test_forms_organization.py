from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-decidim"
TASKS = ROLE / "tasks" / "01_setup.yml"
SERVICES = ROLE / ROLE_FILE_META_SERVICES
FORMS = ROLE / ROLE_FILE_META_FORMS
LOADER = ROLE / "templates" / "javascript.js.j2"
SQL = ROLE / "files" / "sql" / "select" / "organization.sql"
SINK = "DECIDIM_ORGANIZATION"
DRIFT = "tasks/utils/forms/drift.yml"
RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
WRITES = {
    "ruby/ensure/organization.rb": ("host", "users_registration_mode"),
    "ruby/ensure/registration_mode.rb": ("users_registration_mode",),
    "ruby/set_organization_host.rb": ("host",),
    "ruby/configure_oidc.rb": ("omniauth_settings_openid_connect_enabled",),
}
STORED = {
    "host": "decidim.example.org",
    "users_registration_mode": "existing",
    "omniauth_settings_openid_connect_enabled": "true",
}
LOGIN = "services.decidim.login.method"


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(TASKS), trusted_as_template=True)


def _stdin(task: dict) -> str:
    return str(task.get("args", {}).get("stdin", ""))


def _write(tasks: list[dict], script: str) -> int:
    return next(index for index, task in enumerate(tasks) if script in _stdin(task))


def _report(tasks: list[dict]) -> int:
    return next(
        index
        for index, task in enumerate(tasks)
        if DRIFT in str(task.get("ansible.builtin.include_tasks", ""))
    )


def _mode(native: bool, registration: bool) -> str:
    expression = load_yaml_any(str(SERVICES))["decidim"]["organization"][
        "users_registration_mode"
    ]
    flags = {
        f"{LOGIN}.native.enabled": native,
        f"{LOGIN}.registration.enabled": registration,
    }
    env = NativeEnvironment()
    env.filters["bool"] = bool
    return env.from_string(expression).render(
        lookup=lambda _plugin, _role, path: flags[path]
    )


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_store_is_read_and_reported_before_every_enforced_write(self) -> None:
        tasks = _tasks()
        read = next(
            index for index, task in enumerate(tasks) if "database_query" in task
        )
        report = _report(tasks)
        self.assertLess(read, report)
        for script in list(WRITES)[1:]:
            with self.subTest(script=script):
                self.assertLess(report, _write(tasks, script))

    def test_every_write_takes_its_values_from_the_sink(self) -> None:
        tasks = _tasks()
        templar = Templar(
            loader=DataLoader(),
            variables={
                SINK: {
                    "host": "decidim.sink.example",
                    "users_registration_mode": "disabled",
                    "omniauth_settings_openid_connect_enabled": True,
                },
                "ENVIRONMENT": "production",
                "DECIDIM_LOCAL_CID": "cid",
                "DECIDIM_ORGANIZATION_NAME": "Org",
            },
        )
        expected = {
            "host": "DECIDIM_ORG_HOST=decidim.sink.example",
            "users_registration_mode": "DECIDIM_USERS_REGISTRATION_MODE=disabled",
            "omniauth_settings_openid_connect_enabled": "DECIDIM_OIDC_LOGIN_ENABLED=true",
        }
        for script, fields in WRITES.items():
            command = templar.template(
                tasks[_write(tasks, script)]["ansible.builtin.shell"]
            )
            for field in fields:
                with self.subTest(script=script, field=field):
                    self.assertIn(expected[field], command)

    def test_the_report_reads_what_the_store_returned(self) -> None:
        expression = _tasks()[_report(_tasks())]["vars"]["forms_drift_current"][
            "organization"
        ]
        for rows, current in (
            ([['{"host": "decidim.example.org"}']], {"host": "decidim.example.org"}),
            ([["{}"]], {}),
            ([[""]], {}),
        ):
            with self.subTest(rows=rows):
                templar = Templar(
                    loader=DataLoader(),
                    variables={"decidim_organization_stored": {"rows": rows}},
                )
                self.assertEqual(current, templar.template(expression))

    def test_the_read_maps_the_stored_mode_to_its_name(self) -> None:
        sql = read_text(str(SQL))
        for stored, name in (("0", "enabled"), ("1", "existing"), ("2", "disabled")):
            with self.subTest(stored=stored):
                self.assertIn(f"WHEN '{stored}' THEN '{name}'", sql)
        self.assertIn("jsonb_typeof", sql)


class TestTheOrganizationForm(unittest.TestCase):
    def test_the_registration_mode_follows_the_native_and_registration_switches(
        self,
    ) -> None:
        for native, registration, mode in (
            (True, True, "enabled"),
            (True, False, "existing"),
            (False, True, "disabled"),
            (False, False, "disabled"),
        ):
            with self.subTest(native=native, registration=registration):
                self.assertEqual(mode, _mode(native, registration))

    def test_the_oidc_switch_applies_only_with_sso(self) -> None:
        forms = load_yaml_any(str(FORMS))
        for sso, fields in (
            (True, set(STORED)),
            (False, {"host", "users_registration_mode"}),
        ):
            with self.subTest(sso=sso):
                application = {
                    "services": {
                        "sso": {"enabled": sso},
                        "decidim": {
                            "organization": {
                                "host": STORED["host"],
                                "users_registration_mode": STORED[
                                    "users_registration_mode"
                                ],
                            },
                            "login": {"method": {"sso": {"enabled": True}}},
                        },
                    }
                }
                self.assertEqual(
                    fields, set(values("organization", forms, application, {}))
                )

    def test_the_loader_renders_the_shared_lock(self) -> None:
        self.assertIn(RENDERER, read_text(str(LOADER)))
        services = load_yaml_any(str(SERVICES))
        self.assertIs(True, services["javascript"]["enabled"])


if __name__ == "__main__":
    unittest.main()
