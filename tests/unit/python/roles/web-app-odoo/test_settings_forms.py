from __future__ import annotations

import json
import re
import unittest
from typing import TYPE_CHECKING

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.roles.applications.converge import values

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLE = PROJECT_ROOT / "roles" / "web-app-odoo"
TASKS = ROLE / "tasks"
SQL = ROLE / "files" / "sql"
DRIFT = "tasks/utils/forms/drift.yml"
RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
PROVIDER_SQL = (
    SQL / "oidc" / "update" / "keycloak-provider.sql",
    SQL / "oidc" / "insert" / "keycloak-provider.sql",
)
NAMED_ARG = re.compile(r"%\((\w+)\)s")
JSON_KEY = re.compile(r"^\s*'(\w+)',", re.MULTILINE)


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _forms() -> dict:
    return _yaml(ROLE / "meta" / "forms.yml")


def _tasks(path: Path) -> list[dict]:
    return DataLoader().load_from_file(str(path), trusted_as_template=True)


def _render(expression, **variables):
    return Templar(loader=DataLoader(), variables=variables).template(expression)


def _task(path: Path, predicate) -> dict:
    return next(task for task in _tasks(path) if predicate(task))


def _upsert(path: Path, key: str) -> dict:
    def writes(task: dict) -> bool:
        named = task.get("database_query", {}).get("named_args")
        return isinstance(named, dict) and named.get("key") == key

    return _task(path, writes)


def _application(registration: bool, native: bool, sso: bool = True) -> dict:
    return {
        "services": {
            "sso": {"enabled": sso},
            "odoo": {
                "login": {
                    "method": {
                        "registration": {"enabled": registration},
                        "native": {"enabled": native},
                        "sso": {"enabled": sso},
                    }
                },
                "base_url": {
                    "parameters": ["web.base.url"],
                    "value": "https://odoo.example",
                },
                "base_url_freeze": {
                    "parameters": ["web.base.url.freeze"],
                    "value": "True",
                },
                "oauth": {
                    "providers": ["Keycloak"],
                    "client_id": "odoo",
                    "body": "Login with SSO",
                    "css_class": "fa fa-fw fa-key",
                    "auth_endpoint": "https://sso.example/auth",
                    "scope": "openid email profile phone",
                    "validation_endpoint": "https://sso.example/userinfo",
                    "data_endpoint": "https://sso.example/userinfo",
                },
            },
        },
    }


class TestTheFormsMapTheLoginMethods(unittest.TestCase):
    def test_the_general_form_stores_what_the_role_wrote_before(self) -> None:
        for registration, native in ((True, True), (False, False), (True, False)):
            with self.subTest(registration=registration, native=native):
                self.assertEqual(
                    {
                        "auth_signup_uninvited": "b2c" if registration else "b2b",
                        "auth_signup_reset_password": "True" if native else "False",
                    },
                    values("general", _forms(), _application(registration, native), {}),
                )

    def test_the_sso_forms_apply_only_with_sso(self) -> None:
        for form in ("base_url", "base_url_freeze", "oauth_provider"):
            with self.subTest(form=form):
                self.assertNotEqual(
                    {}, values(form, _forms(), _application(True, True), {})
                )
                self.assertEqual(
                    {}, values(form, _forms(), _application(True, True, False), {})
                )

    def test_the_provider_form_holds_exactly_the_columns_the_role_writes(self) -> None:
        fields = set(_forms()["oauth_provider"]["fields"])
        for path in PROVIDER_SQL:
            with self.subTest(sql=path.name):
                self.assertEqual(
                    fields, set(NAMED_ARG.findall(path.read_text(encoding="utf-8")))
                )
        read = (SQL / "oidc" / "select" / "keycloak" / "provider-fields.sql").read_text(
            encoding="utf-8"
        )
        self.assertEqual(fields, set(JSON_KEY.findall(read)))

    def test_the_record_names_the_provider_the_role_writes(self) -> None:
        providers = _yaml(ROLE / "meta" / "services.yml")["odoo"]["oauth"]["providers"]
        self.assertEqual(
            "services.odoo.oauth.providers",
            _forms()["oauth_provider"]["record"]["source"],
        )
        for path in (
            *PROVIDER_SQL,
            SQL / "oidc" / "select" / "keycloak" / "provider-fields.sql",
        ):
            with self.subTest(sql=path.name):
                self.assertEqual(
                    providers,
                    re.findall(r"'(Keycloak)'", path.read_text(encoding="utf-8")),
                )

    def test_the_settings_read_returns_exactly_the_declared_fields(self) -> None:
        read = (SQL / "select" / "managed-settings.sql").read_text(encoding="utf-8")
        declared = {
            key
            for form in ("general", "base_url", "base_url_freeze")
            for key in [form, *_forms()[form]["fields"]]
        }
        self.assertEqual(declared, set(JSON_KEY.findall(read)))


class TestTheConvergeWritesTheSinks(unittest.TestCase):
    def test_the_signup_settings_come_from_the_general_sink(self) -> None:
        tasks = TASKS / "08_login_methods.yml"
        sink = {"auth_signup_uninvited": "b2c", "auth_signup_reset_password": "False"}
        for key, field in (
            ("auth_signup.invitation_scope", "auth_signup_uninvited"),
            ("auth_signup.reset_password", "auth_signup_reset_password"),
        ):
            with self.subTest(key=key):
                expression = _upsert(tasks, key)["database_query"]["named_args"]
                self.assertEqual(
                    sink[field],
                    _render(expression["value"], ODOO_SIGNUP_SETTINGS=sink),
                )
        website = _task(
            tasks,
            lambda task: (
                "website-signup-scope.sql"
                in str(task.get("database_query", {}).get("query_file", ""))
            ),
        )
        self.assertEqual(
            "b2c",
            _render(
                website["database_query"]["named_args"]["scope"],
                ODOO_SIGNUP_SETTINGS=sink,
            ),
        )

    def test_the_base_url_comes_from_its_sink(self) -> None:
        sink = {"web_base_url": "https://odoo.example", "web_base_url_freeze": "True"}
        for key, field in (
            ("web.base.url", "web_base_url"),
            ("web.base.url.freeze", "web_base_url_freeze"),
        ):
            with self.subTest(key=key):
                expression = _upsert(TASKS / "05_oidc.yml", key)["database_query"]
                self.assertEqual(
                    sink[field],
                    _render(expression["named_args"]["value"], ODOO_BASE_URL=sink),
                )

    def test_the_provider_is_written_from_its_sink(self) -> None:
        sink = values("oauth_provider", _forms(), _application(True, True), {})
        for sql in ("update/keycloak-provider.sql", "insert/keycloak-provider.sql"):
            with self.subTest(sql=sql):
                task = _task(
                    TASKS / "05_oidc.yml",
                    lambda task, sql=sql: str(
                        task.get("database_query", {}).get("query_file", "")
                    ).endswith(sql),
                )
                self.assertEqual(
                    sink,
                    _render(
                        task["database_query"]["named_args"], ODOO_OAUTH_PROVIDER=sink
                    ),
                )


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_report_runs_before_every_write(self) -> None:
        steps = [
            task.get("include_tasks") for task in _yaml(TASKS / "01_manager_ops.yml")
        ]
        report = steps.index("utils/settings_drift.yml")
        self.assertLess(report, steps.index("05_oidc.yml"))
        self.assertLess(report, steps.index("08_login_methods.yml"))

    def test_the_report_reads_what_the_store_returned(self) -> None:
        tasks = _tasks(TASKS / "utils" / "settings_drift.yml")
        report = next(
            task
            for task in tasks
            if DRIFT in str(task.get("ansible.builtin.include_tasks", ""))
        )
        self.assertLess(
            max(index for index, task in enumerate(tasks) if "database_query" in task),
            tasks.index(report),
        )
        stored = {
            "general": {"auth_signup_uninvited": "b2b"},
            "base_url": {},
            "base_url_freeze": {},
        }
        for provider, expected in (
            ({"rows": [['{"client_id": "odoo"}']]}, {"client_id": "odoo"}),
            ({"skipped": True}, {}),
        ):
            with self.subTest(provider=provider):
                self.assertEqual(
                    {**stored, "oauth_provider": expected},
                    _render(
                        report["vars"]["forms_drift_current"],
                        odoo_managed_settings_stored={"rows": [[json.dumps(stored)]]},
                        odoo_oauth_provider_stored=provider,
                    ),
                )


class TestTheRendererLocksTheForms(unittest.TestCase):
    def test_the_role_loads_the_shared_renderer_on_every_page(self) -> None:
        self.assertIn(
            RENDERER,
            (ROLE / "templates" / "javascript.js.j2").read_text(encoding="utf-8"),
        )
        self.assertIs(
            True, _yaml(ROLE / "meta" / "services.yml")["javascript"]["enabled"]
        )


if __name__ == "__main__":
    unittest.main()
