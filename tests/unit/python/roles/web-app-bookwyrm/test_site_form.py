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

APPLICATION = "web-app-bookwyrm"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
SITE_TASKS = ROLE / "tasks" / "01_site.yml"
DRIFT_TASKS = "tasks/utils/forms/drift.yml"
LABEL = "Books on example.test"


class _Design(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        if list(terms) != [APPLICATION]:
            raise AssertionError(f"read {terms}, not {APPLICATION}")
        return [{"label": LABEL, "title": False, "name": "BookWyrm"}]


def _render(expression, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _site_block() -> dict:
    tasks = load_yaml_any(str(SITE_TASKS), default_if_missing=[])
    return next(task for task in tasks if "block" in task)


def _site(application: dict) -> dict:
    forms = load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})
    return values("site", forms, application, {})


class TestSiteForm(unittest.TestCase):
    def test_the_computed_site_name_is_the_design_label(self) -> None:
        services = DataLoader().load_from_file(
            str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
        )
        real_get = lookup_loader.get

        def get(name, *args, **kwargs):
            return _Design() if name == "design" else real_get(name, *args, **kwargs)

        templar = Templar(loader=DataLoader(), variables={})
        with mock.patch.object(lookup_loader, "get", side_effect=get):
            rendered = templar.template(services["bookwyrm"]["site_name"])
        self.assertEqual(LABEL, rendered)

    def test_the_site_form_carries_the_site_name_while_the_design_is_on(
        self,
    ) -> None:
        for enabled, expected in ((True, {"site_name": LABEL}), (False, {})):
            application = {
                "services": {
                    "design": {"enabled": enabled},
                    "bookwyrm": {"site_name": LABEL},
                }
            }
            with self.subTest(enabled=enabled):
                self.assertEqual(expected, _site(application))

    def test_the_sink_reads_only_the_site_form(self) -> None:
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'site') }}",
            variables["BOOKWYRM_SITE"],
        )

    def test_the_converge_takes_the_site_name_only_from_the_site_form(self) -> None:
        site_name = _site_block()["vars"]["bookwyrm_site_environment"]["SITE_NAME"]
        self.assertNotIn("lookup(", site_name)
        for settings, expected in (({"site_name": LABEL}, LABEL), ({}, "")):
            with self.subTest(settings=settings):
                self.assertEqual(expected, _render(site_name, BOOKWYRM_SITE=settings))

    def test_the_drift_report_runs_between_the_read_and_the_write(self) -> None:
        read, pending = _site_block()["block"]
        report, write = pending["block"]
        self.assertIn("'MODE': 'read'", read["environment"])
        self.assertEqual("false", str(read["changed_when"]).lower())
        self.assertIn(DRIFT_TASKS, report["ansible.builtin.include_tasks"])
        self.assertIn("'MODE': 'converge'", write["environment"])
        for step in (read, write):
            self.assertIn("-e MODE ", step["ansible.builtin.shell"]["cmd"])
        self.assertEqual("bookwyrm_site_state.pending | bool", pending["when"])

    def test_the_state_is_the_json_line_of_the_read(self) -> None:
        state = _site_block()["vars"]["bookwyrm_site_state"]
        stdout = (
            "12 objects imported automatically\n"
            '{"pending": true, "site_name": "Book Club"}'
        )
        self.assertEqual(
            {"pending": True, "site_name": "Book Club"},
            _render(state, bookwyrm_site_stored={"stdout": stdout}),
        )

    def test_the_drift_report_holds_the_stored_name_only_when_one_is_written(
        self,
    ) -> None:
        current = _site_block()["block"][1]["block"][0]["vars"]["forms_drift_current"]
        state = {"pending": True, "site_name": "Book Club"}
        for site_name, expected in (
            (LABEL, {"site": {"site_name": "Book Club"}}),
            ("", {}),
        ):
            with self.subTest(site_name=site_name):
                self.assertEqual(
                    expected,
                    _render(
                        current,
                        bookwyrm_site_state=state,
                        bookwyrm_site_environment={"SITE_NAME": site_name},
                    ),
                )


if __name__ == "__main__":
    unittest.main()
