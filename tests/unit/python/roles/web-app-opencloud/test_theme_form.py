from __future__ import annotations

import json
import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.applications.forms import locks
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

APPLICATION = "web-app-opencloud"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VARS = ROLE / ROLE_FILE_VARS_MAIN
THEME = ROLE / "templates" / "theme.json.j2"
DESIGN_TASKS = ROLE / "tasks" / "design.yml"
DRIFT_TASKS = "tasks/utils/forms/drift.yml"
LABEL = "Files on example.test"
LOGO = "/opt/design/web-app-opencloud/logo.svg"


class _Design(LookupBase):
    def __init__(self, logo) -> None:
        super().__init__()
        self._logo = logo

    def run(self, terms, variables=None, **kwargs):
        if list(terms) != [APPLICATION]:
            raise AssertionError(f"read {terms}, not {APPLICATION}")
        return [{"label": LABEL, "title": LABEL, "logo": self._logo}]


def _forms() -> dict:
    return load_yaml_any(str(FORMS), default_if_missing={})


def _application(design: bool, logo) -> dict:
    return {
        "services": {
            "design": {"enabled": design},
            "opencloud": {"theme": {"name": LABEL, "slogan": LABEL, "logo": logo}},
        }
    }


def _render(expression, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _theme_json(theme: dict) -> dict:
    variables = load_yaml_any(str(VARS))
    return json.loads(
        _render(
            read_text(str(THEME)),
            OPENCLOUD_THEME=theme,
            **{
                name: _render(variables[name], OPENCLOUD_DESIGN_THEME_ID="infinito")
                for name in (
                    "OPENCLOUD_DESIGN_THEME_URL_PATH",
                    "OPENCLOUD_UPSTREAM_THEME_URL_PATH",
                    "OPENCLOUD_DESIGN_ROLES",
                    "OPENCLOUD_DESIGN_ICON_COLORS",
                )
            },
        )
    )


def _design_tasks() -> list[dict]:
    return load_yaml_any(str(DESIGN_TASKS), default_if_missing=[])


def _index(fragment: str) -> int:
    return next(
        index
        for index, task in enumerate(_design_tasks())
        if fragment in json.dumps(task)
    )


class TestThemeForm(unittest.TestCase):
    def test_the_computed_theme_is_the_design_label_and_logo(self) -> None:
        services = DataLoader().load_from_file(str(SERVICES), trusted_as_template=True)
        real_get = lookup_loader.get
        for logo in (LOGO, False):
            with self.subTest(logo=logo):

                def get(name, *args, logo=logo, **kwargs):
                    if name == "design":
                        return _Design(logo)
                    return real_get(name, *args, **kwargs)

                templar = Templar(loader=DataLoader(), variables={})
                with mock.patch.object(lookup_loader, "get", side_effect=get):
                    theme = templar.template(services["opencloud"]["theme"])
                self.assertEqual({"name": LABEL, "slogan": LABEL, "logo": logo}, theme)

    def test_the_form_carries_the_theme_while_the_design_is_on(self) -> None:
        for design, logo, expected in (
            (True, LOGO, {"name": LABEL, "slogan": LABEL, "logo": LOGO}),
            (True, False, {"name": LABEL, "slogan": LABEL}),
            (False, LOGO, {}),
        ):
            with self.subTest(design=design, logo=logo):
                self.assertEqual(
                    expected,
                    values("theme", _forms(), _application(design, logo), {}),
                )

    def test_opencloud_renders_the_theme_read_only_itself(self) -> None:
        forms = _forms()
        self.assertIs(True, forms["theme"]["native"])
        self.assertEqual(
            [], locks(APPLICATION, forms, _application(True, LOGO), {}, {})
        )

    def test_the_sink_reads_only_the_theme_form(self) -> None:
        self.assertEqual(
            "{{ lookup('form_values', application_id, 'theme') }}",
            load_yaml_any(str(VARS))["OPENCLOUD_THEME"],
        )

    def test_the_theme_file_takes_every_managed_value_from_the_sink(self) -> None:
        for theme, assets in (
            ({"name": LABEL, "slogan": LABEL, "logo": LOGO}, "themes/infinito/assets/"),
            ({"name": LABEL, "slogan": LABEL}, "themes/opencloud/assets/"),
        ):
            with self.subTest(logo="logo" in theme):
                rendered = _theme_json(theme)
                self.assertEqual(LABEL, rendered["common"]["name"])
                self.assertEqual(LABEL, rendered["common"]["slogan"])
                self.assertEqual(assets + "logo.svg", rendered["common"]["logo"])
                self.assertEqual(
                    assets + "logo.svg", rendered["clients"]["web"]["defaults"]["logo"]
                )

    def test_the_logo_set_follows_the_sink(self) -> None:
        slurp = _design_tasks()[_index("ansible.builtin.slurp")]
        for theme, expected in (({"logo": LOGO}, True), ({}, False)):
            with self.subTest(logo="logo" in theme):
                self.assertIs(
                    expected,
                    _render("{{ " + slurp["when"] + " }}", OPENCLOUD_THEME=theme),
                )

    def test_the_drift_report_runs_after_the_read_and_before_the_install(
        self,
    ) -> None:
        read = _index("opencloud_theme_held")
        report = _index(DRIFT_TASKS)
        install = _index("theme.json.j2")
        self.assertLess(read, report)
        self.assertLess(report, install)
        task = _design_tasks()[read]
        self.assertEqual("opencloud_theme_held", task["register"])
        self.assertIs(False, task["failed_when"])
        current = _design_tasks()[report]["vars"]
        held = {"common": {"name": "Edited", "slogan": "Old slogan", "logo": "x"}}
        common = _render(
            current["opencloud_theme_common"],
            opencloud_theme_held={"stdout": json.dumps(held)},
        )
        self.assertEqual(
            {"name": "Edited", "slogan": "Old slogan"},
            {
                field: _render(expression, opencloud_theme_common=common)
                for field, expression in current["forms_drift_current"]["theme"].items()
            },
        )
        self.assertEqual(
            "opencloud_theme_held.rc == 0", _design_tasks()[report]["when"]
        )


if __name__ == "__main__":
    unittest.main()
