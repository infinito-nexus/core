from __future__ import annotations

import json
import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-listmonk"
FORMS = ROLE / "meta" / "forms.yml"
VARS = ROLE / "vars" / "main.yml"
TASKS = ROLE / "tasks" / "02_manager_ops.yml"
APPLY = ROLE / "templates" / "sql" / "apply_settings.sql.j2"
READ = ROLE / "files" / "sql" / "select" / "managed_settings.sql"
LOADER = ROLE / "templates" / "javascript.js.j2"
SHARED_RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
DRIFT = "tasks/utils/forms/drift.yml"
GENERAL_SINK = "LISTMONK_GENERAL_SETTINGS"
OIDC_SINK = "LISTMONK_OIDC_SETTINGS"
PREFIX = "LISTMONK_GENERAL_PREFIX"
APPLIED = re.compile(r"\$infinito_settings\$(.*)\$infinito_settings\$", re.DOTALL)


def _vars() -> dict:
    return load_yaml_any(str(VARS))


def _forms() -> dict:
    return load_yaml_any(str(FORMS))


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(TASKS), trusted_as_template=True)


def _render(template: str, variables: dict):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


def _reads(task: dict) -> bool:
    return "managed_settings.sql" in str(task.get("ansible.builtin.shell", {}))


def _reports(task: dict) -> bool:
    return DRIFT in str(task.get("ansible.builtin.include_tasks", ""))


def _applies(task: dict) -> bool:
    return "apply_settings.sql.j2" in str(task.get("ansible.builtin.shell", {}))


class TestTheFormsFile(unittest.TestCase):
    def test_each_general_field_is_the_app_setting_its_selector_names(self) -> None:
        general = _forms()["general"]
        prefix = _vars()[PREFIX]
        self.assertEqual([GENERAL_SINK], general["sinks"])
        for field, spec in general["fields"].items():
            with self.subTest(field=field):
                self.assertIn(f'[name="{prefix}{field}"]', spec["selector"])

    def test_the_oidc_fields_apply_with_sso_and_leave_the_secret_out(self) -> None:
        security = _forms()["security"]
        self.assertEqual([OIDC_SINK], security["sinks"])
        self.assertNotIn("client_secret", security["fields"])
        for field, spec in security["fields"].items():
            with self.subTest(field=field):
                self.assertEqual("services.sso.enabled", spec["when"])


class TestTheWriteReadsTheSinks(unittest.TestCase):
    def test_the_sinks_read_only_their_forms(self) -> None:
        variables = _vars()
        for sink, form in ((GENERAL_SINK, "general"), (OIDC_SINK, "security")):
            with self.subTest(sink=sink):
                self.assertEqual(
                    f"{{{{ lookup('form_values', application_id, '{form}') }}}}",
                    variables[sink],
                )

    def test_no_general_field_is_written_outside_its_sink(self) -> None:
        variables = _vars()
        managed = {variables[PREFIX] + field for field in _forms()["general"]["fields"]}
        written = {setting["key"] for setting in variables["LISTMONK_SETTINGS"]}
        self.assertEqual(set(), managed & written)

    def test_the_apply_writes_each_general_field_under_its_setting(self) -> None:
        rendered = _render(
            APPLY.read_text(encoding="utf-8"),
            {
                "LISTMONK_SETTINGS": [{"key": "bounce.enabled", "value": "true"}],
                GENERAL_SINK: {"root_url": "https://lists.example", "lang": "de"},
                PREFIX: _vars()[PREFIX],
            },
        )
        self.assertEqual(
            {
                "bounce.enabled": True,
                "app.root_url": "https://lists.example",
                "app.lang": "de",
            },
            json.loads(APPLIED.search(rendered).group(1)),
        )

    def test_the_oidc_setting_is_the_sink_plus_the_client_secret(self) -> None:
        entry = next(
            setting
            for setting in _vars()["LISTMONK_SETTINGS"]
            if setting["key"] == "security.oidc"
        )
        sink = {
            "enabled": True,
            "provider_url": "https://sso.example/realms/main",
            "client_id": "listmonk",
            "auto_create_users": False,
        }
        rendered = _render(
            entry["value"],
            {OIDC_SINK: sink, "OIDC": {"CLIENT": {"SECRET": "probe-secret"}}},
        )
        self.assertEqual(
            {**sink, "client_secret": "probe-secret"}, json.loads(rendered)
        )


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_store_is_read_and_reported_before_the_write(self) -> None:
        tasks = _tasks()
        self.assertLess(_index(tasks, _reads), _index(tasks, _reports))
        self.assertLess(_index(tasks, _reports), _index(tasks, _applies))

    def test_the_read_asks_for_exactly_the_general_sink_fields(self) -> None:
        read = next(task for task in _tasks() if _reads(task))
        command = _render(
            read["ansible.builtin.shell"]["cmd"],
            {
                "LISTMONK_EXEC_DATABASE": "psql",
                PREFIX: "app.",
                GENERAL_SINK: {"root_url": "https://lists.example", "lang": "de"},
            },
        )
        self.assertIn("-v prefix=app.", command)
        self.assertIn("""-v general='["root_url", "lang"]'""", command)

    def test_the_read_never_returns_the_client_secret(self) -> None:
        sql = READ.read_text(encoding="utf-8")
        self.assertIn(":'prefix'", sql)
        self.assertIn(":'general'", sql)
        self.assertIn("value - 'client_secret'", sql)

    def test_the_report_reads_what_the_store_returned(self) -> None:
        report = next(task for task in _tasks() if _reports(task))
        stored = {"general": {"lang": "en"}, "security": {"enabled": True}}
        self.assertEqual(
            stored,
            _render(
                report["vars"]["forms_drift_current"],
                {"listmonk_settings_stored": {"stdout": json.dumps(stored)}},
            ),
        )


class TestTheSettingsPageIsLocked(unittest.TestCase):
    def test_the_loader_includes_the_shared_renderer(self) -> None:
        self.assertIn(SHARED_RENDERER, LOADER.read_text(encoding="utf-8"))

    def test_the_javascript_service_is_literally_on(self) -> None:
        services = load_yaml_any(str(ROLE / "meta" / "services.yml"))
        self.assertIs(True, services["javascript"]["enabled"])


if __name__ == "__main__":
    unittest.main()
