from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SERVICES

ROLE = PROJECT_ROOT / "roles" / "web-app-zammad"
TASKS = ROLE / "tasks" / "01_manager_ops.yml"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
LDAP_SQL = ROLE / "files" / "sql" / "select" / "ldap-source.sql"
EMAIL_SQL = ROLE / "files" / "sql" / "select" / "email-channel.sql"
DRIFT = "tasks/utils/forms/drift.yml"
SECRET = "not-in-the-report"
LDAP = {"host": "ldap.example", "port": 389}
EMAIL = {
    "inbound_host": "imap.example",
    "inbound_port": 143,
    "outbound_host": "smtp.example",
    "outbound_port": 587,
}
SQL_PATTERN = re.compile(r"regexp_match\(([a-z.]+), '((?:[^']|'')*)'\)")
DUMP = """
require "json"
require "yaml"
puts({
  "ldap" => {"host" => "ldap.example", "port" => 389, "bind_pw" => ARGV[0],
             "user_attributes" => {"host" => "x", "port" => "y"}}.to_yaml,
  "email" => {
    "inbound" => {"adapter" => "imap", "options" => {
      "host" => "imap.example", "port" => 143, "password" => ARGV[0]}},
    "outbound" => {"adapter" => "smtp", "options" => {
      "host" => "smtp.example", "port" => 587, "password" => ARGV[0]}},
  }.to_yaml,
}.to_json)
"""


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(TASKS), trusted_as_template=True)


def _steps() -> list[dict]:
    """Returns:
    the tasks in run order, each child of a guarded block carrying the
    condition of its block.
    """
    return [
        {**step, "when": task["when"]} if "when" in task and "block" in task else step
        for task in _tasks()
        for step in task.get("block", [task])
    ]


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


def _reads(sql: str):
    return lambda task: sql in str(task.get("database_query", {}).get("query_file", ""))


def _reports(form: str):
    return lambda task: (
        DRIFT in str(task.get("ansible.builtin.include_tasks", ""))
        and form in task.get("vars", {}).get("forms_drift_current", {})
    )


def _writes(script: str):
    def predicate(task: dict) -> bool:
        shell = task.get("ansible.builtin.shell")
        return isinstance(shell, dict) and script in str(shell.get("stdin", ""))

    return predicate


def _patterns(sql) -> dict[str, list[re.Pattern]]:
    found: dict[str, list[re.Pattern]] = {}
    for column, pattern in SQL_PATTERN.findall(read_text(str(sql))):
        found.setdefault(column, []).append(re.compile(pattern.replace("''", "'")))
    return found


def _first(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_each_form_is_read_and_reported_before_its_write(self) -> None:
        tasks = _steps()
        for sql, form, script in (
            ("ldap-source.sql", "ldap", "ldap_source.rb"),
            ("email-channel.sql", "email", "email_channel.rb"),
        ):
            with self.subTest(form=form):
                read = _index(tasks, _reads(sql))
                report = _index(tasks, _reports(form))
                write = _index(tasks, _writes(script))
                self.assertLess(read, report)
                self.assertLess(report, write)
                self.assertEqual(
                    {str(tasks[write]["when"])},
                    {str(tasks[read]["when"]), str(tasks[report]["when"])},
                )

    def test_the_writes_take_host_and_port_from_the_sinks(self) -> None:
        tasks = _steps()
        templar = Templar(
            loader=DataLoader(),
            variables={"ZAMMAD_LDAP_SOURCE": LDAP, "ZAMMAD_EMAIL_CHANNEL": EMAIL},
        )
        for script, wanted in (
            ("ldap_source.rb", {"LDAP_HOST": "ldap.example", "LDAP_PORT": "389"}),
            (
                "email_channel.rb",
                {
                    "IMAP_HOST": "imap.example",
                    "IMAP_PORT": "143",
                    "SMTP_HOST": "smtp.example",
                    "SMTP_PORT": "587",
                },
            ),
        ):
            environment = tasks[_index(tasks, _writes(script))]["environment"]
            for name, value in wanted.items():
                with self.subTest(name=name):
                    self.assertEqual(value, str(templar.template(environment[name])))


@unittest.skipIf(shutil.which("ruby") is None, "ruby is not installed")
class TestTheReadsParseTheRailsStoreYaml(unittest.TestCase):
    def setUp(self) -> None:
        result = subprocess.run(
            ["ruby", "-e", DUMP, SECRET],
            capture_output=True,
            text=True,
            check=True,
        )
        self.stored = json.loads(result.stdout)

    def test_the_ldap_read_takes_the_top_level_host_and_port(self) -> None:
        patterns = _patterns(LDAP_SQL)["latest.preferences"]
        found = [_first(pattern, self.stored["ldap"]) for pattern in patterns]
        self.assertEqual(["ldap.example", "389"], found)

    def test_the_email_read_takes_host_and_port_per_direction(self) -> None:
        patterns = _patterns(EMAIL_SQL)
        blocks = {
            direction: _first(pattern, self.stored["email"])
            for direction, pattern in zip(
                ("inbound", "outbound"), patterns["latest.options"], strict=True
            )
        }
        found = [
            _first(patterns["inbound.block"][0], blocks["inbound"]),
            _first(patterns["inbound.block"][1], blocks["inbound"]),
            _first(patterns["outbound.block"][0], blocks["outbound"]),
            _first(patterns["outbound.block"][1], blocks["outbound"]),
        ]
        self.assertEqual(["imap.example", "143", "smtp.example", "587"], found)
        self.assertNotIn(SECRET, " ".join(found))


class TestTheFormsFollowTheServices(unittest.TestCase):
    def test_the_forms_apply_only_with_their_service(self) -> None:
        forms = load_yaml_any(str(FORMS))
        for enabled in (True, False):
            application = {
                "services": {
                    "ldap": {"enabled": enabled},
                    "email": {"enabled": enabled},
                    "zammad": {"ldap_source": LDAP, "email_channel": EMAIL},
                }
            }
            with self.subTest(enabled=enabled):
                self.assertEqual(
                    LDAP if enabled else {}, values("ldap", forms, application, {})
                )
                self.assertEqual(
                    EMAIL if enabled else {}, values("email", forms, application, {})
                )

    def test_the_outbound_source_stays_empty_without_the_email_service(self) -> None:
        channel = load_yaml_any(str(SERVICES))["zammad"]["email_channel"]

        def render(key: str, enabled: bool) -> str:
            def lookup(name: str, *terms, key: str = "") -> object:
                if name == "config":
                    return enabled
                assert name == "email"
                return {"host": "smtp.example", "port": "587"}[key]

            env = Environment(autoescape=True)
            env.filters["bool"] = bool
            env.filters["int"] = int
            return env.from_string(str(channel[key])).render(lookup=lookup)

        self.assertEqual(
            ["smtp.example", "587", "", "0"],
            [
                render("outbound_host", True),
                render("outbound_port", True),
                render("outbound_host", False),
                render("outbound_port", False),
            ],
        )


if __name__ == "__main__":
    unittest.main()
