from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_FORMS

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-gitlab"
SCRIPT = ROLE / "files" / "ruby" / "apply_login_methods.rb"
TASKS = ROLE / "tasks" / "utils" / "login_methods.yml"
SQL = ROLE / "files" / "sql" / "select" / "application-settings.sql"
SINK = "GITLAB_APPLICATION_SETTINGS"
OBJSTORE = "GITLAB_OBJSTORE_ENABLED"
LIVE_TRACE = "ci_job_live_trace_enabled"
LIVE_TRACE_STORED = {
    "password_authentication_enabled_for_web": True,
    "signup_enabled": True,
    LIVE_TRACE: True,
}
LIVE_TRACE_WANTED = {
    "password_authentication_enabled_for_web": True,
    "signup_enabled": False,
}
DRIFT = "tasks/utils/forms/drift.yml"

STUBS = """
require 'json'

UPDATES = []

class StubSettings
  def initialize(values)
    @values = values
  end

  def public_send(key)
    @values.fetch(key.to_s)
  end

  def update!(changes)
    UPDATES << changes
  end
end

module ApplicationSetting
  def self.current_without_cache
    StubSettings.new(JSON.parse(ENV.fetch('STUB_STORED')))
  end
end

at_exit { STDERR.puts(JSON.generate(UPDATES)) }
"""


def _run(
    stored: dict,
    wanted: dict,
    second_factor: str = "false",
    enforced: str = "false",
    objstore: str = "true",
):
    env = {
        "PATH": os.environ["PATH"],
        "STUB_STORED": json.dumps(stored),
        SINK: json.dumps(wanted),
        "GITLAB_LOGIN_2FA": second_factor,
        "GITLAB_LOGIN_2FA_ENFORCED": enforced,
        OBJSTORE: objstore,
    }
    program = STUBS + f"eval(File.read({json.dumps(str(SCRIPT))}), TOPLEVEL_BINDING)\n"
    result = subprocess.run(
        ["ruby", "-e", program],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, json.loads(result.stderr.strip().splitlines()[-1])


def _tasks() -> list[dict]:
    return DataLoader().load_from_file(str(TASKS), trusted_as_template=True)


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


@unittest.skipIf(shutil.which("ruby") is None, "ruby is not installed")
class TestTheRunnerWritesTheGeneralForm(unittest.TestCase):
    def test_only_the_settings_that_differ_are_written(self) -> None:
        result, updates = _run(
            {"password_authentication_enabled_for_web": True, "signup_enabled": False},
            {"password_authentication_enabled_for_web": False, "signup_enabled": False},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([{"password_authentication_enabled_for_web": False}], updates)
        self.assertIn("[CHANGED]", result.stdout)

    def test_a_store_that_holds_the_form_stays_untouched(self) -> None:
        result, updates = _run(
            {"password_authentication_enabled_for_web": False, "signup_enabled": True},
            {"password_authentication_enabled_for_web": False, "signup_enabled": True},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], updates)
        self.assertIn("[UNCHANGED]", result.stdout)

    def test_the_second_factor_still_follows_its_own_switch(self) -> None:
        result, updates = _run(
            {
                "password_authentication_enabled_for_web": True,
                "signup_enabled": False,
                "require_two_factor_authentication": False,
                "two_factor_grace_period": 48,
            },
            {"password_authentication_enabled_for_web": True, "signup_enabled": False},
            second_factor="true",
            enforced="true",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [{"require_two_factor_authentication": True, "two_factor_grace_period": 0}],
            updates,
        )


@unittest.skipIf(shutil.which("ruby") is None, "ruby is not installed")
class TestTheWriteStaysValidWithoutObjectStorage(unittest.TestCase):
    def test_incremental_logging_follows_the_object_storage(self) -> None:
        converged = {**LIVE_TRACE_STORED, "signup_enabled": False}
        for objstore, stored, expected in (
            (
                "false",
                LIVE_TRACE_STORED,
                [{"signup_enabled": False, LIVE_TRACE: False}],
            ),
            ("false", converged, [{LIVE_TRACE: False}]),
            ("true", LIVE_TRACE_STORED, [{"signup_enabled": False}]),
            ("false", {**converged, LIVE_TRACE: False}, []),
        ):
            with self.subTest(objstore=objstore, stored=stored):
                result, updates = _run(stored, LIVE_TRACE_WANTED, objstore=objstore)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, updates)


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_store_is_read_and_reported_before_the_write(self) -> None:
        tasks = _tasks()
        read = _index(tasks, lambda task: "database_query" in task)
        report = _index(
            tasks,
            lambda task: DRIFT in str(task.get("ansible.builtin.include_tasks", "")),
        )
        write = _index(tasks, lambda task: SINK in task.get("environment", {}))
        self.assertLess(read, report)
        self.assertLess(report, write)

    def test_the_write_hands_the_sink_to_the_runner(self) -> None:
        write = next(task for task in _tasks() if SINK in task.get("environment", {}))
        self.assertIn(SINK, write["ansible.builtin.command"]["argv"])
        templar = Templar(
            loader=DataLoader(),
            variables={SINK: {"signup_enabled": False}},
        )
        self.assertEqual(
            {"signup_enabled": False},
            json.loads(templar.template(write["environment"][SINK])),
        )

    def test_the_write_hands_the_object_storage_state_to_the_runner(self) -> None:
        write = next(task for task in _tasks() if SINK in task.get("environment", {}))
        self.assertIn(OBJSTORE, write["ansible.builtin.command"]["argv"])
        for enabled, handed in ((True, "true"), (False, "false")):
            with self.subTest(enabled=enabled):
                templar = Templar(loader=DataLoader(), variables={OBJSTORE: enabled})
                self.assertEqual(
                    handed, templar.template(write["environment"][OBJSTORE])
                )

    def test_the_read_asks_for_exactly_the_sink_fields(self) -> None:
        read = next(task for task in _tasks() if "database_query" in task)
        templar = Templar(
            loader=DataLoader(),
            variables={
                SINK: {
                    "password_authentication_enabled_for_web": True,
                    "signup_enabled": False,
                },
            },
        )
        self.assertEqual(
            ["password_authentication_enabled_for_web", "signup_enabled"],
            json.loads(
                templar.template(read["database_query"]["named_args"]["fields"])
            ),
        )
        self.assertIn("%(fields)s", read_text(str(SQL)))

    def test_the_report_reads_what_the_store_returned(self) -> None:
        report = next(
            task
            for task in _tasks()
            if DRIFT in str(task.get("ansible.builtin.include_tasks", ""))
        )
        expression = report["vars"]["forms_drift_current"]["general"]
        for rows, current in (
            ([['{"signup_enabled": true}']], {"signup_enabled": True}),
            ([[""]], {}),
        ):
            with self.subTest(rows=rows):
                templar = Templar(
                    loader=DataLoader(),
                    variables={"gitlab_application_settings_stored": {"rows": rows}},
                )
                self.assertEqual(current, templar.template(expression))

    def test_every_sink_field_is_a_declared_field_of_the_general_form(self) -> None:
        forms = load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS))
        self.assertEqual([SINK], forms["general"]["sinks"])
        self.assertEqual(
            {"password_authentication_enabled_for_web", "signup_enabled"},
            set(forms["general"]["fields"]),
        )


if __name__ == "__main__":
    unittest.main()
