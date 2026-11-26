from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import jinja2
from ansible.parsing.dataloader import DataLoader
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.dotenv import FilterModule
from utils.cache import PROJECT_ROOT

ENV = PROJECT_ROOT / "tasks" / "utils" / "forms" / "env.yml"
WHOLE_FILE_READERS = ("slurp", "fetch", "b64decode", "lookup('file'", 'lookup("file"')
FIELDS = {"gf_auth_basic_enabled": "true", "gf_users_allow_sign_up": "false"}
CONTENT = (
    'GF_SECURITY_ADMIN_PASSWORD="hunter2"\n'
    'GF_AUTH_BASIC_ENABLED="true"\n'
    '  GF_USERS_ALLOW_SIGN_UP="false"\n'
    'GF_AUTH_BASIC_ENABLED_EXTRA="x"\n'
)
NAMED = {"webserver_domain": "pi.hole"}
NAMED_SPECS = {"webserver_domain": {"env": "FTLCONF_webserver_domain"}}
NAMED_CONTENT = (
    'FTLCONF_webserver_api_password="hunter2"\n'
    'FTLCONF_webserver_domain="pi.hole"\n'
    'FTLCONF_WEBSERVER_DOMAIN="upper"\n'
    'WEBSERVER_DOMAIN="key"\n'
)


def _block() -> dict:
    return DataLoader().load_from_file(str(ENV), trusted_as_template=True)[0]


def _tasks() -> list[dict]:
    return _block()["block"]


def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    env.filters.update(FilterModule().filters())
    return env


def _read_task() -> dict:
    return next(task for task in _tasks() if "ansible.builtin.command" in task)


def _argv(path: str, fields: dict = FIELDS, specs: dict | None = None) -> list[str]:
    env = _environment()
    return [
        env.from_string(
            str(part).replace(
                "lookup('container', application_id, 'files.env')", "path"
            )
        ).render(forms_env_fields=fields, forms_env_specs=specs or {}, path=path)
        for part in _read_task()["ansible.builtin.command"]["argv"]
    ]


def _report() -> dict:
    return next(task for task in _tasks() if "ansible.builtin.include_tasks" in task)


def _held(stdout: str, fields: dict, specs: dict | None = None) -> dict:
    env = NativeEnvironment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    env.filters.update(FilterModule().filters())
    current = env.from_string(_report()["vars"]["forms_drift_current"]).render(
        forms_env_form="settings",
        forms_env_held={"stdout": stdout},
        forms_env_fields=fields,
        forms_env_specs=specs or {},
        DEPLOYMENT_MODE="compose",
    )
    return current["settings"]


class TestTheEnvReadTakesOnlyTheManagedLines(unittest.TestCase):
    def test_no_task_reads_or_registers_the_whole_env_file(self) -> None:
        for task in _tasks():
            text = json.dumps(task)
            with self.subTest(task=task.get("name")):
                for reader in WHOLE_FILE_READERS:
                    self.assertNotIn(reader, text)

    def test_the_read_selects_exactly_the_managed_variables(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / ".env"
            path.write_text(CONTENT, encoding="utf-8")
            result = subprocess.run(
                _argv(str(path)), capture_output=True, text=True, check=False
            )
        self.assertEqual(0, result.returncode)
        self.assertNotIn("PASSWORD", result.stdout)
        self.assertNotIn("hunter2", result.stdout)
        self.assertEqual(FIELDS, _held(result.stdout, FIELDS))

    def test_a_field_reads_the_variable_its_env_names(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / ".env"
            path.write_text(NAMED_CONTENT, encoding="utf-8")
            result = subprocess.run(
                _argv(str(path), NAMED, NAMED_SPECS),
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(0, result.returncode)
        self.assertEqual('FTLCONF_webserver_domain="pi.hole"\n', result.stdout)
        self.assertEqual(NAMED, _held(result.stdout, NAMED, NAMED_SPECS))

    def test_the_read_and_the_report_name_the_variables_from_the_form(self) -> None:
        self.assertEqual(
            "{{ lookup('config', application_id, 'forms.' ~ forms_env_form ~ '.fields') }}",
            _block()["vars"]["forms_env_specs"],
        )
        self.assertIn(
            "dotenv_names(forms_env_specs)",
            json.dumps(_read_task()["ansible.builtin.command"]["argv"]),
        )
        self.assertIn(
            "dotenv_fields(forms_env_fields, forms_env_specs)",
            _report()["vars"]["forms_drift_current"],
        )

    def test_a_missing_env_file_skips_the_report_without_failing(self) -> None:
        result = subprocess.run(
            _argv("/nonexistent/.env"), capture_output=True, text=True, check=False
        )
        self.assertEqual(2, result.returncode)
        task = _read_task()
        self.assertEqual("forms_env_held.rc > 2", task["failed_when"])
        self.assertEqual("forms_env_held.rc | default(2) in [0, 1]", _report()["when"])

    def test_the_read_is_a_masked_grep_that_changes_nothing(self) -> None:
        task = _read_task()
        self.assertEqual("grep", task["ansible.builtin.command"]["argv"][0])
        self.assertEqual("{{ MASK_CREDENTIALS_IN_LOGS | bool }}", task["no_log"])
        self.assertIs(False, task["changed_when"])


if __name__ == "__main__":
    unittest.main()
