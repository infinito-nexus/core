from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import jinja2
from ansible.parsing.dataloader import DataLoader

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


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(ENV), trusted_as_template=True)


def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    env.filters.update(FilterModule().filters())
    return env


def _read_task() -> dict:
    return next(task for task in _tasks() if "ansible.builtin.command" in task)


def _argv(path: str) -> list[str]:
    env = _environment()
    return [
        env.from_string(
            str(part).replace(
                "lookup('container', application_id, 'files.env')", "path"
            )
        ).render(forms_env_fields=FIELDS, path=path)
        for part in _read_task()["ansible.builtin.command"]["argv"]
    ]


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
        held = json.loads(
            _environment()
            .from_string("{{ stdout | dotenv_fields(fields) | tojson }}")
            .render(stdout=result.stdout, fields=FIELDS, DEPLOYMENT_MODE="compose")
        )
        self.assertEqual(FIELDS, held)

    def test_a_missing_env_file_skips_the_report_without_failing(self) -> None:
        result = subprocess.run(
            _argv("/nonexistent/.env"), capture_output=True, text=True, check=False
        )
        self.assertEqual(2, result.returncode)
        task = _read_task()
        self.assertEqual("forms_env_held.rc > 2", task["failed_when"])
        report = next(
            task for task in _tasks() if "ansible.builtin.include_tasks" in task
        )
        self.assertEqual("forms_env_held.rc | default(2) in [0, 1]", report["when"])

    def test_the_read_is_a_masked_grep_that_changes_nothing(self) -> None:
        task = _read_task()
        self.assertEqual("grep", task["ansible.builtin.command"]["argv"][0])
        self.assertEqual("{{ MASK_CREDENTIALS_IN_LOGS | bool }}", task["no_log"])
        self.assertIs(False, task["changed_when"])

    def test_the_param_doc_keeps_the_keys_lower_snake_case(self) -> None:
        header = ENV.read_text(encoding="utf-8").split("\n- ", 1)[0]
        self.assertRegex(header, re.compile(r"lower snake_case"))


if __name__ == "__main__":
    unittest.main()
