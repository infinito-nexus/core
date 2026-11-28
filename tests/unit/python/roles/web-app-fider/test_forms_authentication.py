from __future__ import annotations

import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-fider"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VARS = ROLE / ROLE_FILE_VARS_MAIN
TENANT = ROLE / "tasks" / "01_tenant.yml"
OIDC = ROLE / "tasks" / "02_setup_oidc.yml"
SQL = ROLE / "files" / "sql"
UPSERT = SQL / "configure-oidc-provider.sql"
READ_PROVIDER = SQL / "select" / "oauth-provider.sql"
READ_EMAIL_AUTH = SQL / "select" / "email-auth.sql"
WRITE_EMAIL_AUTH = SQL / "email-auth.sql"
LOADER = ROLE / "templates" / "javascript.js.j2"
SHARED_RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
DRIFT = "tasks/utils/forms/drift.yml"
SINKS = {
    "authentication": "FIDER_AUTHENTICATION",
    "oauth_provider": "FIDER_OAUTH_PROVIDER",
}
NAMED_ARG = re.compile(r"%\((\w+)\)s")
JSON_KEY = re.compile(r"'(\w+)',\s*\w+")
SECRET_ARG = "client_secret"


def _forms() -> dict:
    return load_yaml_any(str(FORMS))


def _fields(form: str) -> set[str]:
    return set(_forms()[form]["fields"])


def _tasks(path) -> list[dict]:
    return DataLoader().load_from_file(str(path), trusted_as_template=True)


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


def _query_file(task: dict) -> str:
    return str(task.get("database_query", {}).get("query_file", ""))


def _role_path(path) -> str:
    return f"/{path.relative_to(ROLE).as_posix()}"


def _render(expression, variables: dict):
    return Templar(loader=DataLoader(), variables=variables).template(expression)


def _application(sso: bool, native: bool) -> dict:
    services = load_yaml_any(str(SERVICES))
    oauth = {
        key: f"rendered {key}" if isinstance(value, str) and "{{" in value else value
        for key, value in services["fider"]["oauth"].items()
    }
    return {
        "forms": _forms(),
        "services": {
            "sso": {"enabled": True},
            "fider": {
                "login": {
                    "method": {
                        "sso": {"enabled": sso},
                        "native": {"enabled": native},
                    }
                },
                "oauth": oauth,
            },
        },
    }


class TestTheFormsFileDeclaresTheAuthenticationPage(unittest.TestCase):
    def test_each_form_names_its_own_sink_and_the_sink_reads_only_that_form(self):
        sinks = load_yaml_any(str(VARS))
        for form, sink in SINKS.items():
            with self.subTest(form=form):
                self.assertEqual([sink], _forms()[form]["sinks"])
                self.assertEqual(
                    f"{{{{ lookup('form_values', application_id, '{form}') }}}}",
                    sinks[sink],
                )

    def test_the_provider_form_locks_only_the_keycloak_provider(self):
        form = _forms()["oauth_provider"]
        oauth = load_yaml_any(str(SERVICES))["fider"]["oauth"]
        self.assertEqual(
            form["fields"]["client_id"]["selector"], form["record"]["selector"]
        )
        self.assertEqual("services.fider.oauth.client_ids", form["record"]["source"])
        self.assertEqual([oauth["client_id"]], oauth["client_ids"])

    def test_the_status_switch_maps_the_sso_method_to_fider_status(self):
        for sso, status in ((True, 2), (False, 1)):
            with self.subTest(sso=sso):
                application = _application(sso=sso, native=True)
                provider = values(
                    "oauth_provider", application["forms"], application, {}
                )
                self.assertEqual(status, provider["status"])
                self.assertIs(True, provider["is_trusted"])
                self.assertEqual("openid profile email", provider["scope"])

    def test_the_email_switch_follows_the_native_method(self):
        for native in (True, False):
            with self.subTest(native=native):
                application = _application(sso=True, native=native)
                self.assertEqual(
                    {"is_email_auth_allowed": native},
                    values("authentication", application["forms"], application, {}),
                )

    def test_the_lock_renderer_is_loaded_on_every_page(self):
        services = load_yaml_any(str(SERVICES))
        self.assertIs(True, services["javascript"]["enabled"])
        self.assertIn(SHARED_RENDERER, read_text(str(LOADER)))


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def _order(self, path, read: str, write: str) -> None:
        tasks = _tasks(path)
        first = _index(tasks, lambda task: _query_file(task).endswith(read))
        report = _index(
            tasks,
            lambda task: DRIFT in str(task.get("ansible.builtin.include_tasks", "")),
        )
        last = _index(tasks, lambda task: _query_file(task).endswith(write))
        self.assertLess(first, report)
        self.assertLess(report, last)

    def test_the_email_switch_is_read_and_reported_before_the_write(self):
        self._order(TENANT, _role_path(READ_EMAIL_AUTH), _role_path(WRITE_EMAIL_AUTH))

    def test_the_provider_is_read_and_reported_before_the_upsert(self):
        self._order(OIDC, _role_path(READ_PROVIDER), _role_path(UPSERT))

    def test_each_read_selects_exactly_the_fields_of_its_form(self):
        for path, form in (
            (READ_EMAIL_AUTH, "authentication"),
            (READ_PROVIDER, "oauth_provider"),
        ):
            with self.subTest(form=form):
                text = read_text(str(path))
                self.assertEqual(_fields(form), set(JSON_KEY.findall(text)))
                self.assertNotIn(SECRET_ARG, text)

    def test_each_report_reads_what_the_store_returned(self):
        for path, form, register in (
            (TENANT, "authentication", "fider_email_auth_stored"),
            (OIDC, "oauth_provider", "fider_oauth_provider_stored"),
        ):
            report = next(
                task
                for task in _tasks(path)
                if DRIFT in str(task.get("ansible.builtin.include_tasks", ""))
            )
            for stored, current in (('{"status": 1}', {"status": 1}), ("{}", {})):
                with self.subTest(form=form, stored=stored):
                    self.assertEqual(
                        current,
                        _render(
                            report["vars"]["forms_drift_current"][form],
                            {register: {"rows": [[stored]]}},
                        ),
                    )


class TestTheWriteTakesTheManagedValuesFromTheSinks(unittest.TestCase):
    def test_every_upsert_value_but_the_secret_comes_from_the_provider_sink(self):
        write = next(
            task for task in _tasks(OIDC) if _query_file(task).endswith(UPSERT.name)
        )
        arguments = write["database_query"]["named_args"]
        self.assertEqual(
            set(NAMED_ARG.findall(read_text(str(UPSERT)))),
            set(arguments),
        )
        managed = {name for name in arguments if name != SECRET_ARG}
        self.assertEqual(_fields("oauth_provider"), managed)
        sink = {name: f"value of {name}" for name in managed}
        for name in managed:
            with self.subTest(argument=name):
                self.assertEqual(
                    f"value of {name}",
                    _render(arguments[name], {SINKS["oauth_provider"]: sink}),
                )

    def test_the_email_switch_is_written_from_the_authentication_sink(self):
        write = next(
            task
            for task in _tasks(TENANT)
            if _query_file(task).endswith(_role_path(WRITE_EMAIL_AUTH))
        )
        for allowed, rendered in ((True, "true"), (False, "false")):
            with self.subTest(allowed=allowed):
                self.assertEqual(
                    rendered,
                    _render(
                        write["database_query"]["named_args"]["allowed"],
                        {SINKS["authentication"]: {"is_email_auth_allowed": allowed}},
                    ),
                )


if __name__ == "__main__":
    unittest.main()
