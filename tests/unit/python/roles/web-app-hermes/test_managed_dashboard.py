from __future__ import annotations

import json
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.filter.mcp.authorization import FilterModule as McpFilterModule
from plugins.filter.mcp.credentials import mcp_with_credentials
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import dump_yaml_str, load_yaml_any, load_yaml_str
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TASKS_MCP,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles/web-app-hermes"
TEMPLATE = ROLE / "templates/config.yaml.j2"
TASKS = ROLE / ROLE_FILE_TASKS_MCP
SAMPLE = {"theme": "sample-theme", "trusted_proxies": ["198.51.100.0/24"]}
UNMANAGED = ["203.0.113.0/24"]
TOKEN = "hermes-sample-token"
SERVER = {
    "id": "web-app-gitea",
    "url": "http://gitea:3000/mcp",
    "auth": "bearer_token",
    "transport": "streamable-http",
    "tools": ["list_repos"],
    "mutating": [],
}
DISCOVERED = {**SERVER, "token": TOKEN, "owner": "mcp-gitea", "login": "mcp"}


def _forms() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})


def _application(webui: bool, theme: object, mcp: bool) -> dict:
    return {
        "mcp": {"enabled": mcp},
        "services": {
            "hermes": {
                "dashboard": {**SAMPLE, "theme": theme},
                "mcp_servers": {"selected": [SERVER]},
            },
            "webui": {"enabled": webui},
        },
    }


def _sink(webui: bool, theme: object = SAMPLE["theme"]) -> dict:
    return values("dashboard", _forms(), _application(webui, theme, False), {})


def _mcp_sink(mcp: bool) -> dict:
    return values("mcp", _forms(), _application(False, False, mcp), {})


def _rendered(webui: bool, sink: dict, servers: list) -> dict:
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters.update(McpFilterModule().filters())
    environment.filters.update({"to_json": json.dumps, "bool": bool})
    document = environment.from_string(read_text(str(TEMPLATE))).render(
        HERMES_MCP_SERVERS=servers,
        HERMES_WEBUI_ENABLED=webui,
        HERMES_DASHBOARD_CONFIG=sink,
        HERMES_DESIGN_THEME_ENABLED=webui,
        HERMES_DESIGN_THEME="corporate",
        NETWORK_TRUSTED_PROXY_CIDRS=UNMANAGED,
    )
    return {"document": document, "parsed": load_yaml_str(document)}


def _drift_read(document: str, sink: dict, mcp: dict) -> dict:
    declared = DataLoader().load_from_file(str(TASKS), trusted_as_template=True)
    task_vars = next(
        task
        for task in declared
        if str(task["name"]).startswith("📣 Report the managed settings")
    )["vars"]
    templar = Templar(
        loader=DataLoader(),
        variables={
            **task_vars,
            "hermes_config_held": {"stdout": document, "rc": 0},
            "HERMES_DASHBOARD_CONFIG": sink,
            "HERMES_MCP_CONFIG": mcp,
        },
    )
    return templar.template(task_vars["forms_drift_current"])


class TestManagedDashboard(unittest.TestCase):
    def test_the_render_writes_every_managed_field_where_the_drift_reads_it(
        self,
    ) -> None:
        for theme in (SAMPLE["theme"], False):
            with self.subTest(theme=theme):
                sink = _sink(True, theme)
                rendered = _rendered(True, sink, [])
                self.assertEqual(sink, rendered["parsed"]["dashboard"])
                self.assertEqual(
                    {"dashboard": sink, "mcp": {}},
                    _drift_read(rendered["document"], sink, {}),
                )

    def test_a_switched_off_title_theme_leaves_the_theme_to_the_dashboard(
        self,
    ) -> None:
        self.assertEqual(["trusted_proxies"], list(_sink(True, False)))

    def test_without_the_dashboard_nothing_is_managed_or_rendered(self) -> None:
        self.assertEqual({}, _sink(False))
        self.assertNotIn("dashboard", _rendered(False, {}, [])["parsed"])

    def test_the_drift_read_keeps_only_the_managed_keys(self) -> None:
        held = dump_yaml_str(
            {"dashboard": {"theme": "edited", "port": 1}, "model": {"default": "x"}},
            sort_keys=True,
        )
        self.assertEqual(
            {"dashboard": {"theme": "edited"}, "mcp": {}},
            _drift_read(held, _sink(True), {}),
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
        read = next(i for i, name in enumerate(names) if "Read the managed" in name)
        report = next(i for i, name in enumerate(names) if "Report the managed" in name)
        render = next(i for i, name in enumerate(names) if "Render the Hermes" in name)
        self.assertLess(read, report)
        self.assertLess(report, render)


class TestManagedMcpServers(unittest.TestCase):
    def test_the_servers_converge_only_with_the_mcp_client_on(self) -> None:
        self.assertEqual({"servers": [SERVER]}, _mcp_sink(True))
        self.assertEqual({}, _mcp_sink(False))

    def test_the_render_writes_every_managed_server_where_the_drift_reads_it(
        self,
    ) -> None:
        mcp = _mcp_sink(True)
        servers = mcp_with_credentials(mcp["servers"], [DISCOVERED])
        rendered = _rendered(False, {}, servers)
        self.assertEqual(
            {"dashboard": {}, "mcp": mcp},
            _drift_read(rendered["document"], {}, mcp),
        )

    def test_the_rendered_config_references_the_token_and_never_holds_it(
        self,
    ) -> None:
        mcp = _mcp_sink(True)
        servers = mcp_with_credentials(mcp["servers"], [DISCOVERED])
        document = _rendered(False, {}, servers)["document"]
        self.assertNotIn(TOKEN, document)
        self.assertIn("${env:WEB_APP_GITEA_MCP_TOKEN}", document)

    def test_the_drift_read_sees_a_moved_and_a_hand_added_server(self) -> None:
        mcp = _mcp_sink(True)
        held = dump_yaml_str(
            {
                "mcp_servers": {
                    "web_app_gitea": {"url": "http://moved/mcp"},
                    "manual": {"url": "http://manual/mcp"},
                }
            },
            sort_keys=True,
        )
        self.assertEqual(
            [
                {**SERVER, "url": "http://moved/mcp"},
                {"id": "manual", "url": "http://manual/mcp"},
            ],
            _drift_read(held, {}, mcp)["mcp"]["servers"],
        )

    def test_the_render_takes_the_servers_from_the_form(self) -> None:
        declared = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertIn("HERMES_MCP_CONFIG", declared["HERMES_MCP_SERVERS"])
        self.assertNotIn("lookup('config'", declared["HERMES_MCP_SERVERS"])


if __name__ == "__main__":
    unittest.main()
