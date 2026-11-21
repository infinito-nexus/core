from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SERVICES

ROLE = PROJECT_ROOT / "roles" / "web-app-zammad"
SCRIPT = ROLE / "files" / "ruby" / "apply" / "login_methods.rb"
TASKS = ROLE / "tasks" / "01_manager_ops.yml"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
SINK = "ZAMMAD_SECURITY"
DRIFT = "tasks/utils/forms/drift.yml"
WANTED = {
    "auth_openid_connect": True,
    "user_show_password_login": False,
    "user_create_account": False,
}

STUBS = """
require 'json'

WRITES = []

module UserInfo
  def self.current_user_id=(id); end
end

module Setting
  def self.set(name, value)
    WRITES << [name, value]
  end
end

module Role
  def self.where(**)
    self
  end

  def self.pluck(*)
    [2, 1]
  end
end

at_exit { STDERR.puts(JSON.generate(WRITES)) }
"""


def _run(wanted: dict):
    env = {
        "PATH": os.environ["PATH"],
        SINK: json.dumps(wanted),
        "LOGIN_2FA": "true",
        "LOGIN_2FA_ENFORCED": "false",
    }
    program = STUBS + f"eval(File.read({json.dumps(str(SCRIPT))}), TOPLEVEL_BINDING)\n"
    result = subprocess.run(
        ["ruby", "-e", program], env=env, capture_output=True, text=True, check=False
    )
    return result, json.loads(result.stderr.strip().splitlines()[-1])


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(TASKS), trusted_as_template=True)


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


def _is_report(task: dict) -> bool:
    return DRIFT in str(
        task.get("ansible.builtin.include_tasks", "")
    ) and "security" in task.get("vars", {}).get("forms_drift_current", {})


def _is_write(task: dict) -> bool:
    shell = task.get("ansible.builtin.shell")
    return isinstance(shell, dict) and "login_methods.rb" in str(shell.get("stdin", ""))


def _templar(**variables):
    return Templar(loader=DataLoader(), variables=variables)


@unittest.skipIf(shutil.which("ruby") is None, "ruby is not installed")
class TestTheScriptWritesTheSecurityForm(unittest.TestCase):
    def test_every_sink_field_is_set_before_the_second_factor(self) -> None:
        result, writes = _run(WANTED)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([[name, value] for name, value in WANTED.items()], writes[:3])
        self.assertEqual(
            ["two_factor_authentication_method_authenticator_app", True], writes[3]
        )


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_store_is_read_and_reported_before_the_write(self) -> None:
        tasks = _tasks()
        read = _index(
            tasks,
            lambda task: (
                "settings.sql"
                in str(task.get("database_query", {}).get("query_file", ""))
            ),
        )
        report = _index(tasks, _is_report)
        write = _index(tasks, _is_write)
        self.assertLess(read, report)
        self.assertLess(report, write)

    def test_the_read_asks_for_exactly_the_sink_fields(self) -> None:
        read = next(
            task
            for task in _tasks()
            if "settings.sql"
            in str(task.get("database_query", {}).get("query_file", ""))
        )
        self.assertEqual(
            sorted(WANTED),
            sorted(
                json.loads(
                    _templar(**{SINK: WANTED}).template(
                        read["database_query"]["named_args"]["fields"]
                    )
                )
            ),
        )

    def test_the_report_reads_the_json_the_query_aggregates(self) -> None:
        expression = next(task for task in _tasks() if _is_report(task))["vars"][
            "forms_drift_current"
        ]["security"]
        for rows, current in (
            ([['{"user_create_account": true}']], {"user_create_account": True}),
            ([[""]], {}),
        ):
            with self.subTest(rows=rows):
                templar = _templar(zammad_security_stored={"rows": rows})
                self.assertEqual(current, templar.template(expression))

    def test_the_write_hands_the_sink_to_the_script(self) -> None:
        write = next(task for task in _tasks() if _is_write(task))
        self.assertIn("-e ZAMMAD_SECURITY", write["ansible.builtin.shell"]["cmd"])
        self.assertEqual(
            WANTED,
            json.loads(_templar(**{SINK: WANTED}).template(write["environment"][SINK])),
        )


class TestTheFormFollowsTheLoginMethods(unittest.TestCase):
    def _password_form(self, native: bool, ldap: bool) -> str:
        def lookup(name: str, application_id: str, path: str) -> bool:
            assert name == "config"
            return {"native": native, "ldap": ldap}[path.split(".")[-2]]

        expression = load_yaml_any(str(SERVICES))["zammad"]["login"]["password_form"]
        env = Environment(autoescape=True)
        env.filters["bool"] = bool
        return env.from_string(str(expression)).render(lookup=lookup)

    def test_the_password_form_stays_while_native_or_ldap_is_on(self) -> None:
        for native, ldap, wanted in (
            (True, False, "True"),
            (False, True, "True"),
            (False, False, "False"),
        ):
            with self.subTest(native=native, ldap=ldap):
                self.assertEqual(wanted, self._password_form(native, ldap))

    def test_the_form_maps_the_login_methods(self) -> None:
        application = {
            "services": {
                "zammad": {
                    "login": {
                        "method": {
                            "sso": {"enabled": True},
                            "registration": {"enabled": False},
                        },
                        "password_form": False,
                    }
                }
            }
        }
        self.assertEqual(
            WANTED, values("security", load_yaml_any(str(FORMS)), application, {})
        )

    def test_the_javascript_service_is_on_literally(self) -> None:
        self.assertIs(True, load_yaml_any(str(SERVICES))["javascript"]["enabled"])


if __name__ == "__main__":
    unittest.main()
