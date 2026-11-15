from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_VARS_MAIN
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles" / "web-app-pixelfed"
DESIGN_TASKS = ROLE / "tasks" / "05_design.yml"
DESIGN_SCRIPT = ROLE / "files" / "php" / "design.php"
DRIFT_TASKS = "tasks/utils/forms/drift.yml"
TITLE = "Pictures on example.test"


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _design_block() -> dict:
    tasks = load_yaml_any(str(DESIGN_TASKS), default_if_missing=[])
    return next(task for task in tasks if "block" in task)


def _settings(design: dict) -> dict:
    forms = load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})
    return values("settings", forms, {"services": {"design": design}}, {})


class TestSettingsForm(unittest.TestCase):
    def test_the_settings_form_carries_the_design_title_while_the_design_is_on(
        self,
    ) -> None:
        self.assertEqual(
            {"site_name": TITLE}, _settings({"enabled": True, "title": TITLE})
        )
        self.assertEqual({}, _settings({"enabled": False, "title": TITLE}))

    def test_the_sink_reads_only_the_settings_form(self) -> None:
        sink = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))["PIXELFED_SETTINGS"]
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'settings') }}", sink
        )

    def test_the_converge_takes_the_site_name_only_from_the_settings_form(
        self,
    ) -> None:
        title = _design_block()["vars"]["pixelfed_design_payload"]["title"]
        self.assertNotIn("lookup(", title)
        for settings, expected in (
            ({"site_name": TITLE}, TITLE),
            ({}, ""),
            ({"site_name": False}, ""),
        ):
            with self.subTest(settings=settings):
                self.assertEqual(expected, _render(title, PIXELFED_SETTINGS=settings))

    def test_the_drift_report_runs_between_the_read_and_the_write(self) -> None:
        read, pending = _design_block()["block"]
        report, write = pending["block"]
        self.assertIn("'mode': 'read'", read["ansible.builtin.command"]["stdin"])
        self.assertEqual("false", str(read["changed_when"]).lower())
        self.assertIn(DRIFT_TASKS, report["ansible.builtin.include_tasks"])
        self.assertIn("'mode': 'converge'", write["ansible.builtin.command"]["stdin"])
        self.assertEqual("pixelfed_design_state.pending | bool", pending["when"])

    def test_the_drift_report_holds_the_stored_site_name_only_when_one_is_written(
        self,
    ) -> None:
        current = _design_block()["block"][1]["block"][0]["vars"]["forms_drift_current"]
        state = {"site_name": "Pixelfed", "pending": True}
        self.assertEqual(
            {"settings": {"site_name": "Pixelfed"}},
            _render(
                current,
                pixelfed_design_state=state,
                pixelfed_design_payload={"title": TITLE},
            ),
        )
        self.assertEqual(
            {},
            _render(
                current,
                pixelfed_design_state=state,
                pixelfed_design_payload={"title": ""},
            ),
        )

    def test_the_read_mode_exits_before_any_write(self) -> None:
        script = read_text(str(DESIGN_SCRIPT))
        read = script.index("if ($payload['mode'] === 'read')")
        self.assertLess(read, script.index("ConfigCacheService::put("))
        self.assertIn(
            "exit(0);", script[read : script.index("ConfigCacheService::put(")]
        )


if __name__ == "__main__":
    unittest.main()
