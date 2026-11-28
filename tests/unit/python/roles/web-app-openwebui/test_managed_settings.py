from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import ChainableUndefined, DictLoader, Environment, select_autoescape

from plugins.filter.dotenv import FilterModule as DotenvFilters
from plugins.filter.mcp.credentials import mcp_with_credentials
from plugins.filter.mcp.tool_server_connections import (
    FilterModule as ToolServerFilters,
)
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "web-app-openwebui"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VARS = ROLE / ROLE_FILE_VARS_MAIN
CORE = ROLE / "tasks" / "00_core.yml"
TEMPLATE = ROLE / "templates" / "env.j2"
READER = ROLE / "files" / "python" / "tool_servers_held.py"
ENV_DRIFT = "tasks/utils/forms/env.yml"
SETTINGS = [
    "enable_signup",
    "enable_login_form",
    "default_user_role",
    "offline_mode",
    "hf_hub_offline",
]
TOKEN = "openwebui-sample-token"
SERVER = {
    "id": "web-app-gitea",
    "url": "http://gitea:3000/mcp",
    "auth": "bearer_token",
    "transport": "streamable-http",
    "tools": ["list_repos"],
    "mutating": [],
}
DISCOVERED = {**SERVER, "token": TOKEN, "owner": "mcp-gitea", "login": "mcp"}


def _environment() -> Environment:
    env = Environment(
        loader=DictLoader(
            {
                "env.j2": read_text(str(TEMPLATE)),
                "roles/sys-svc-container/templates/env.j2": "",
            }
        ),
        trim_blocks=True,
        undefined=ChainableUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(DotenvFilters().filters())
    env.filters.update(ToolServerFilters().filters())
    env.filters["bool"] = bool
    env.filters["to_json"] = json.dumps
    return env


def _application(registration: bool, native: bool, offline: bool) -> dict:
    services = copy.deepcopy(load_yaml_any(str(SERVICES)))
    methods = services["openwebui"]["login"]["method"]
    methods["registration"]["enabled"] = registration
    methods["native"]["enabled"] = native
    services["openwebui"]["offline_mode"] = offline
    services["openwebui"]["hf_hub_offline"] = offline
    return {"services": services}


def _settings(registration: bool, native: bool, offline: bool) -> dict:
    forms = load_yaml_any(str(FORMS))
    return values("settings", forms, _application(registration, native, offline), {})


def _env(settings: dict, **variables) -> str:
    return (
        _environment()
        .get_template("env.j2")
        .render(
            OPENWEBUI_SETTINGS=settings,
            OPENWEBUI_ARENA_MODELS=load_yaml_any(str(VARS))["OPENWEBUI_ARENA_MODELS"],
            DEPLOYMENT_MODE="compose",
            lookup=lambda *terms, **kwargs: {},
            **variables,
        )
    )


def _tools(mcp: bool) -> dict:
    application = {
        "mcp": {"enabled": mcp},
        "services": {"openwebui": {"mcp_servers": {"selected": [SERVER]}}},
    }
    return values("tools", load_yaml_any(str(FORMS)), application, {})


def _servers_held(content: str) -> dict:
    spec = importlib.util.spec_from_file_location("tool_servers_held", READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory:
        env_file = Path(directory) / ".env"
        env_file.write_text(content, encoding="utf-8")
        return module.connections(env_file)


def _drift_read(held: dict, tools: dict) -> dict:
    task_vars = next(
        task
        for task in DataLoader().load_from_file(str(CORE), trusted_as_template=True)
        if str(task.get("name")).startswith("📣 Report the MCP tool servers")
    )["vars"]
    templar = Templar(
        loader=DataLoader(),
        variables={
            **task_vars,
            "openwebui_tool_servers_held": {"stdout": json.dumps(held)},
            "OPENWEBUI_MCP_CONFIG": tools,
        },
    )
    return templar.template(task_vars["forms_drift_current"])


def _held(content: str) -> dict:
    forms = load_yaml_any(str(FORMS))
    template = _environment().from_string(
        "{{ content | dotenv_fields(fields, specs) | tojson }}"
    )
    return json.loads(
        template.render(
            content=content,
            fields=SETTINGS,
            specs=forms["settings"]["fields"],
            DEPLOYMENT_MODE="compose",
        )
    )


class TestTheSettingsFormWritesWhatTheEnvWrote(unittest.TestCase):
    def test_every_switch_renders_the_values_the_old_env_rendered(self) -> None:
        for registration in (True, False):
            for native in (True, False):
                for offline in (True, False):
                    with self.subTest(
                        registration=registration, native=native, offline=offline
                    ):
                        settings = _settings(registration, native, offline)
                        self.assertEqual(
                            {
                                "enable_signup": str(registration).lower(),
                                "enable_login_form": str(native).lower(),
                                "default_user_role": "user",
                                "offline_mode": str(int(offline)),
                                "hf_hub_offline": str(int(offline)),
                            },
                            _held(_env(settings)),
                        )

    def test_the_drift_read_takes_back_exactly_what_the_env_writes(self) -> None:
        settings = _settings(False, True, False)
        self.assertEqual(SETTINGS, list(settings))
        self.assertEqual(settings, _held(_env(settings)))


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_env_drift_runs_before_the_stack_renders_the_env_file(self) -> None:
        tasks = DataLoader().load_from_file(str(CORE), trusted_as_template=True)
        drift = next(i for i, task in enumerate(tasks) if ENV_DRIFT in str(task))
        stack = next(
            i
            for i, task in enumerate(tasks)
            if task.get("include_role", {}).get("name") == "svc-stack"
        )
        self.assertLess(drift, stack)
        self.assertEqual("settings", tasks[drift]["vars"]["forms_env_form"])

    def test_the_tool_server_drift_runs_before_the_stack_renders(self) -> None:
        names = [str(task.get("name")) for task in load_yaml_any(str(CORE))]
        read = next(i for i, name in enumerate(names) if "Read the MCP tool" in name)
        report = next(
            i for i, name in enumerate(names) if "Report the MCP tool" in name
        )
        stack = next(i for i, name in enumerate(names) if "load docker" in name)
        self.assertLess(read, report)
        self.assertLess(report, stack)


class TestTheToolServersForm(unittest.TestCase):
    def test_the_servers_converge_only_with_the_mcp_client_on(self) -> None:
        self.assertEqual({"servers": [SERVER]}, _tools(True))
        self.assertEqual({}, _tools(False))

    def test_the_render_writes_every_managed_server_where_the_drift_reads_it(
        self,
    ) -> None:
        tools = _tools(True)
        servers = mcp_with_credentials(tools["servers"], [DISCOVERED])
        content = _env(
            _settings(False, True, False),
            OPENWEBUI_MCP_SERVERS=servers,
            OPENWEBUI_MCP_GROUP_IDS={},
        )
        self.assertIn(TOKEN, content)
        held = _servers_held(content)
        self.assertNotIn(TOKEN, json.dumps(held))
        self.assertEqual({"tools": tools}, _drift_read(held, tools))

    def test_the_drift_read_sees_a_moved_and_a_hand_added_server(self) -> None:
        tools = _tools(True)
        held = {"web-app-gitea": "http://moved/mcp", "manual": "http://x/mcp"}
        self.assertEqual(
            [
                {**SERVER, "url": "http://moved/mcp"},
                {"id": "manual", "url": "http://x/mcp"},
            ],
            _drift_read(held, tools)["tools"]["servers"],
        )

    def test_the_render_takes_the_servers_from_the_form(self) -> None:
        declared = load_yaml_any(str(VARS))["OPENWEBUI_MCP_SERVERS"]
        self.assertIn("OPENWEBUI_MCP_CONFIG", declared)
        self.assertNotIn("lookup('config'", declared)


if __name__ == "__main__":
    unittest.main()
