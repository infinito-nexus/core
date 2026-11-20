from __future__ import annotations

import unittest
import unittest.mock as mock

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

APPLICATION = "web-app-jellyfin"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
CORE_TASKS = ROLE / "tasks" / "00_core.yml"
DESIGN_TASKS = ROLE / "tasks" / "utils" / "design.yml"
DRIFT_TASKS = "tasks/utils/forms/drift.yml"
TITLE = "Media on example.test"


class _Design(LookupBase):
    def __init__(self, title):
        super().__init__()
        self._title = title

    def run(self, terms, variables=None, **kwargs):
        if list(terms) != [APPLICATION]:
            raise AssertionError(f"read {terms}, not {APPLICATION}")
        return [{"title": self._title, "label": self._title or "Jellyfin"}]


def _render(expression, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _computed_server_name(title):
    services = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
    )
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        return _Design(title) if name == "design" else real_get(name, *args, **kwargs)

    templar = Templar(loader=DataLoader(), variables={})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(services["jellyfin"]["server_name"])


def _design_include_vars() -> dict:
    blocks = load_yaml_any(str(CORE_TASKS), default_if_missing=[])
    tasks = [task for block in blocks for task in block.get("block", [])]
    include = next(
        task
        for task in tasks
        if "utils/design.yml" in str(task.get("ansible.builtin.include_tasks"))
    )
    return include["vars"]


def _server_name_steps() -> list[dict]:
    tasks = load_yaml_any(str(DESIGN_TASKS), default_if_missing=[])
    return next(task for task in tasks if "block" in task)["block"]


class TestSettingsForm(unittest.TestCase):
    def test_the_computed_server_name_is_the_design_title(self) -> None:
        self.assertEqual(TITLE, _computed_server_name(TITLE))
        self.assertIs(False, _computed_server_name(False))

    def test_the_settings_form_carries_the_server_name_while_the_design_is_on(
        self,
    ) -> None:
        forms = load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})
        for enabled, expected in ((True, {"server_name": TITLE}), (False, {})):
            application = {
                "services": {
                    "design": {"enabled": enabled},
                    "jellyfin": {"server_name": TITLE},
                }
            }
            with self.subTest(enabled=enabled):
                self.assertEqual(expected, values("settings", forms, application, {}))

    def test_the_sink_reads_only_the_settings_form(self) -> None:
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'settings') }}",
            variables["JELLYFIN_SETTINGS"],
        )

    def test_the_write_takes_the_server_name_only_from_the_settings_form(
        self,
    ) -> None:
        title = _design_include_vars()["jellyfin_design_title"]
        self.assertNotIn("lookup(", title)
        for settings, expected in (
            ({"server_name": TITLE}, TITLE),
            ({"server_name": False}, False),
            ({}, False),
        ):
            with self.subTest(settings=settings):
                self.assertEqual(expected, _render(title, JELLYFIN_SETTINGS=settings))

    def test_the_drift_report_runs_between_the_read_and_the_write(self) -> None:
        read, drifted = _server_name_steps()
        report, write = drifted["block"]
        self.assertEqual("jellyfin_design_system_answer", read["register"])
        self.assertIn(DRIFT_TASKS, report["ansible.builtin.include_tasks"])
        self.assertEqual(
            "jellyfin_design_system.get('ServerName') != jellyfin_design_title",
            drifted["when"],
        )
        self.assertIn("ServerName", write["ansible.builtin.command"]["stdin"])

    def test_the_drift_report_holds_the_stored_server_name(self) -> None:
        current = _server_name_steps()[1]["block"][0]["vars"]["forms_drift_current"]
        self.assertEqual(
            {"settings": {"server_name": "Jellyfin"}},
            _render(current, jellyfin_design_system={"ServerName": "Jellyfin"}),
        )


if __name__ == "__main__":
    unittest.main()
