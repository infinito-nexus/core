from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles" / "web-app-bigbluebutton"
LOGIN_TASKS = ROLE / "tasks" / "04_login_methods.yml"
SCRIPT = ROLE / "files" / "ruby" / "greenlight" / "registration_method.rb"
APPLICATION = "web-app-bigbluebutton"
DRIFT_TASKS = "tasks/utils/forms/drift.yml"
SITE_SETTING_STUB = """
Setting = Struct.new(:value) do
  def update!(value:)
    self.value = value
    File.write(ENV.fetch("WRITES"), value)
  end
end

class SiteSetting
  REGISTRATION_METHODS = { open: "open", invite: "invite", approval: "approval" }.freeze

  def self.joins(*)
    self
  end

  def self.find_by!(**)
    @setting ||= Setting.new(ENV.fetch("STORED"))
  end
end

load ARGV.fetch(0)
"""


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


def _computed_method(sso: bool, sso_login: bool, registration: bool) -> str:
    config = {
        "services.sso.enabled": sso,
        "services.bigbluebutton.login.method.sso.enabled": sso_login,
        "services.bigbluebutton.login.method.registration.enabled": registration,
    }

    def answer(application, path):
        if application != APPLICATION:
            raise AssertionError(f"read {application}, not {APPLICATION}")
        return config[path]

    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        return _Stub(answer) if name == "config" else real_get(name, *args, **kwargs)

    services = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
    )
    templar = Templar(loader=DataLoader(), variables={})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(services["greenlight"]["registration_method"]).strip()


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _converge_block() -> dict:
    tasks = load_yaml_any(str(LOGIN_TASKS), default_if_missing=[])
    return next(task for task in tasks if "block" in task)


def _run_script(mode: str, stored: str, wanted: str) -> tuple[int, str, str | None]:
    with tempfile.TemporaryDirectory() as scratch:
        writes = Path(scratch) / "writes"
        completed = subprocess.run(
            ["ruby", "-e", SITE_SETTING_STUB, str(SCRIPT)],
            env={
                **os.environ,
                "MODE": mode,
                "REGISTRATION_METHOD": wanted,
                "STORED": stored,
                "WRITES": str(writes),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        written = (
            writes.read_text()  # nocheck: cache-read tempdir
            if writes.exists()
            else None
        )
    return completed.returncode, completed.stdout, written


class TestRegistrationForm(unittest.TestCase):
    def test_the_computed_method_opens_registration_for_sso_or_registration(
        self,
    ) -> None:
        for flags, expected in (
            ((True, True, False), "open"),
            ((True, False, False), "invite"),
            ((False, True, False), "invite"),
            ((False, False, True), "open"),
            ((False, False, False), "invite"),
        ):
            with self.subTest(flags=flags):
                self.assertEqual(expected, _computed_method(*flags))

    def test_the_registration_form_carries_the_computed_method(self) -> None:
        forms = load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})
        application = {"services": {"greenlight": {"registration_method": "open"}}}
        self.assertEqual(
            {"registration_method": "open"},
            values("registration", forms, application, {}),
        )

    def test_the_sink_reads_only_the_registration_form(self) -> None:
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'registration') }}",
            variables["BBB_REGISTRATION"],
        )
        self.assertNotIn("BBB_REGISTRATION_METHOD", variables)

    def test_the_drift_report_runs_between_the_read_and_the_write(self) -> None:
        read, pending = _converge_block()["block"]
        report, write = pending["block"]
        self.assertEqual("read", read["environment"]["MODE"])
        self.assertEqual("false", str(read["changed_when"]).lower())
        self.assertIn(DRIFT_TASKS, report["ansible.builtin.include_tasks"])
        self.assertEqual("converge", write["environment"]["MODE"])
        self.assertEqual("bbb_registration_state.pending | bool", pending["when"])
        for step in (read, write):
            self.assertEqual(
                "{{ BBB_REGISTRATION.registration_method }}",
                step["environment"]["REGISTRATION_METHOD"],
            )

    def test_the_drift_report_holds_the_stored_method(self) -> None:
        current = _converge_block()["block"][1]["block"][0]["vars"][
            "forms_drift_current"
        ]
        stored = {"registration_method": "invite", "pending": True}
        self.assertEqual(
            "invite",
            _render(
                current["registration"]["registration_method"],
                bbb_registration_state=stored,
            ),
        )


@unittest.skipUnless(shutil.which("ruby"), "needs a ruby interpreter")
class TestRegistrationMethodScript(unittest.TestCase):
    def test_read_reports_the_stored_method_and_writes_nothing(self) -> None:
        status, stdout, written = _run_script("read", "invite", "open")
        self.assertEqual(0, status)
        self.assertEqual(
            {"registration_method": "invite", "pending": True},
            json.loads(stdout.splitlines()[-1]),
        )
        self.assertIsNone(written)

    def test_read_reports_nothing_pending_once_converged(self) -> None:
        _, stdout, written = _run_script("read", "open", "open")
        self.assertFalse(json.loads(stdout.splitlines()[-1])["pending"])
        self.assertIsNone(written)

    def test_converge_writes_only_a_differing_method(self) -> None:
        _, stdout, written = _run_script("converge", "invite", "open")
        self.assertIn("CHANGED RegistrationMethod=open", stdout)
        self.assertEqual("open", written)
        _, stdout, written = _run_script("converge", "open", "open")
        self.assertIn("NOOP RegistrationMethod=open", stdout)
        self.assertIsNone(written)

    def test_an_unknown_mode_fails_before_any_write(self) -> None:
        status, _, written = _run_script("apply", "invite", "open")
        self.assertNotEqual(0, status)
        self.assertIsNone(written)


if __name__ == "__main__":
    unittest.main()
