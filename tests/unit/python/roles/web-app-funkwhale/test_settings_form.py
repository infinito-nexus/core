from __future__ import annotations

import unittest
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

APPLICATION = "web-app-funkwhale"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
MANAGER_TASKS = ROLE / "tasks" / "01_manager.yml"
DRIFT_TASKS = "tasks/utils/forms/drift.yml"
LABEL = "Music on example.test"
MODE = "FUNKWHALE_DESIGN_MODE"


class _Design(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        if list(terms) != [APPLICATION]:
            raise AssertionError(f"read {terms}, not {APPLICATION}")
        return [{"label": LABEL, "title": False, "name": "Funkwhale"}]


def _render(expression, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _theming_block() -> dict:
    tasks = load_yaml_any(str(MANAGER_TASKS), default_if_missing=[])
    return next(task for task in tasks if "block" in task)


class TestSettingsForm(unittest.TestCase):
    def test_the_computed_instance_name_is_the_design_label(self) -> None:
        services = DataLoader().load_from_file(
            str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
        )
        real_get = lookup_loader.get

        def get(name, *args, **kwargs):
            return _Design() if name == "design" else real_get(name, *args, **kwargs)

        templar = Templar(loader=DataLoader(), variables={})
        with mock.patch.object(lookup_loader, "get", side_effect=get):
            rendered = templar.template(services["funkwhale"]["instance_name"])
        self.assertEqual(LABEL, rendered)

    def test_the_settings_form_carries_the_instance_name_while_the_design_is_on(
        self,
    ) -> None:
        forms = load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})
        for enabled, expected in ((True, {"instance_name": LABEL}), (False, {})):
            application = {
                "services": {
                    "design": {"enabled": enabled},
                    "funkwhale": {"instance_name": LABEL},
                }
            }
            with self.subTest(enabled=enabled):
                self.assertEqual(expected, values("settings", forms, application, {}))

    def test_the_converge_takes_the_instance_name_only_from_the_settings_form(
        self,
    ) -> None:
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'settings') }}",
            variables["FUNKWHALE_SETTINGS"],
        )
        name = variables["FUNKWHALE_DESIGN_PREFERENCES"]["instance__name"]
        self.assertNotIn("lookup(", name)
        for settings, expected in (({"instance_name": LABEL}, LABEL), ({}, "")):
            with self.subTest(settings=settings):
                self.assertEqual(expected, _render(name, FUNKWHALE_SETTINGS=settings))

    def test_the_drift_report_runs_between_the_read_and_the_write(self) -> None:
        read, pending = _theming_block()["block"]
        report, write = pending["block"]
        self.assertIn(f"'{MODE}': 'read'", read["environment"])
        self.assertEqual("false", str(read["changed_when"]).lower())
        self.assertIn(DRIFT_TASKS, report["ansible.builtin.include_tasks"])
        self.assertIn(f"'{MODE}': 'converge'", write["environment"])
        for step in (read, write):
            self.assertIn(MODE, step["ansible.builtin.command"]["argv"])
        self.assertEqual("funkwhale_design_state.pending | bool", pending["when"])

    def test_the_state_is_the_json_line_of_the_read(self) -> None:
        state = _theming_block()["vars"]["funkwhale_design_state"]
        stdout = '3 objects imported\n{"pending": true, "instance_name": "Mine"}'
        self.assertEqual(
            {"pending": True, "instance_name": "Mine"},
            _render(state, funkwhale_design_stored={"stdout": stdout}),
        )

    def test_the_drift_report_holds_the_stored_name_only_while_it_is_managed(
        self,
    ) -> None:
        current = _theming_block()["block"][1]["block"][0]["vars"][
            "forms_drift_current"
        ]
        state = {"pending": True, "instance_name": "Mine"}
        for settings, expected in (
            ({"instance_name": LABEL}, {"settings": {"instance_name": "Mine"}}),
            ({}, {}),
        ):
            with self.subTest(settings=settings):
                self.assertEqual(
                    expected,
                    _render(
                        current,
                        funkwhale_design_state=state,
                        FUNKWHALE_SETTINGS=settings,
                    ),
                )


if __name__ == "__main__":
    unittest.main()
