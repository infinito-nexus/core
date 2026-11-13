from __future__ import annotations

import json
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.filter.mcp.authorization import FilterModule as McpFilterModule
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles/web-app-hermes"
TEMPLATE = ROLE / "templates/config.yaml.j2"
TASKS = ROLE / "tasks/utils/mcp.yml"
SAMPLE = {"theme": "sample-theme", "trusted_proxies": ["198.51.100.0/24"]}
UNMANAGED = ["203.0.113.0/24"]


def _forms() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})


def _sink(webui: bool, theme: object = SAMPLE["theme"]) -> dict:
    application = {
        "services": {
            "hermes": {"dashboard": {**SAMPLE, "theme": theme}},
            "webui": {"enabled": webui},
        }
    }
    return values("dashboard", _forms(), application, {})


def _rendered(webui: bool, sink: dict) -> dict:
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters.update(McpFilterModule().filters())
    environment.filters.update({"to_json": json.dumps, "bool": bool})
    document = environment.from_string(read_text(str(TEMPLATE))).render(
        HERMES_MCP_SERVERS=[],
        HERMES_WEBUI_ENABLED=webui,
        HERMES_DASHBOARD_CONFIG=sink,
        HERMES_DESIGN_THEME_ENABLED=webui,
        HERMES_DESIGN_THEME="corporate",
        NETWORK_TRUSTED_PROXY_CIDRS=UNMANAGED,
    )
    return {"document": document, "parsed": yaml.safe_load(document)}


def _drift_read(document: str, sink: dict) -> dict:
    declared = DataLoader().load_from_file(str(TASKS), trusted_as_template=True)
    expression = next(
        task
        for task in declared
        if str(task["name"]).startswith("📣 Report the dashboard settings")
    )["vars"]["forms_drift_current"]
    templar = Templar(
        loader=DataLoader(),
        variables={
            "hermes_config_held": {"stdout": document, "rc": 0},
            "HERMES_DASHBOARD_CONFIG": sink,
        },
    )
    return templar.template(expression)


class TestManagedDashboard(unittest.TestCase):
    def test_the_render_writes_every_managed_field_where_the_drift_reads_it(
        self,
    ) -> None:
        for theme in (SAMPLE["theme"], False):
            with self.subTest(theme=theme):
                sink = _sink(True, theme)
                rendered = _rendered(True, sink)
                self.assertEqual(sink, rendered["parsed"]["dashboard"])
                self.assertEqual(
                    {"dashboard": sink}, _drift_read(rendered["document"], sink)
                )

    def test_a_switched_off_title_theme_leaves_the_theme_to_the_dashboard(
        self,
    ) -> None:
        self.assertEqual(["trusted_proxies"], list(_sink(True, False)))

    def test_without_the_dashboard_nothing_is_managed_or_rendered(self) -> None:
        self.assertEqual({}, _sink(False))
        self.assertNotIn("dashboard", _rendered(False, {})["parsed"])

    def test_the_drift_read_keeps_only_the_managed_keys(self) -> None:
        held = yaml.safe_dump(
            {"dashboard": {"theme": "edited", "port": 1}, "model": {"default": "x"}}
        )
        self.assertEqual(
            {"dashboard": {"theme": "edited"}},
            _drift_read(held, _sink(True)),
        )

    def test_the_computed_theme_is_the_theme_the_role_ships(self) -> None:
        expression = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))["hermes"][
            "dashboard"
        ]["theme"]
        shipped = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))["HERMES_DESIGN_THEME"]
        environment = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        environment.filters["bool"] = bool
        compiled = environment.compile_expression(
            expression.strip().removeprefix("{{").removesuffix("}}")
        )
        for design, expected in ((True, shipped), (False, False)):
            with self.subTest(design=design):

                def lookup(*terms: str, design: bool = design) -> bool:
                    self.assertEqual(
                        ("config", "web-app-hermes", "services.design.enabled"),
                        terms,
                    )
                    return design

                self.assertEqual(expected, compiled(lookup=lookup))

    def test_the_drift_is_reported_before_the_render(self) -> None:
        names = [task["name"] for task in load_yaml_any(str(TASKS))]
        read = next(i for i, name in enumerate(names) if "Read the dashboard" in name)
        report = next(
            i for i, name in enumerate(names) if "Report the dashboard" in name
        )
        render = next(i for i, name in enumerate(names) if "Render the Hermes" in name)
        self.assertLess(read, report)
        self.assertLess(report, render)


if __name__ == "__main__":
    unittest.main()
