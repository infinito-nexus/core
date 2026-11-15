from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

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
    ROLE_FILE_TASKS_MCP,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles/web-app-openclaw"
TEMPLATE = ROLE / "templates/openclaw.json.j2"
VARS = ROLE / ROLE_FILE_VARS_MAIN
TASKS = ROLE / ROLE_FILE_TASKS_MCP
READER = ROLE / "files/python/config_fields.py"
SAMPLE = {
    "trustedProxies": ["198.51.100.0/24"],
    "mode": "sample-auth-mode",
    "userHeader": "x-sample-user",
    "primary": "litellm/sample-model",
    "baseUrl": "http://gateway.example.test/v1",
}
TOKEN = "openclaw-sample-token"
SERVER = {
    "id": "web-app-gitea",
    "url": "http://gitea:3000/mcp",
    "auth": "bearer_token",
    "transport": "streamable-http",
    "tools": ["list_repos"],
    "mutating": [],
}
DISCOVERED = {**SERVER, "token": TOKEN, "owner": "mcp-gitea", "login": "mcp"}
TEMPLATE_VARS = {
    "OPENCLAW_TRUSTED_PROXY_SOURCES": "trustedProxies",
    "OPENCLAW_TRUSTED_PROXY_MODE": "mode",
    "OPENCLAW_TRUSTED_PROXY_USER_HEADER": "userHeader",
    "OPENCLAW_LITELLM_PRIMARY": "primary",
    "OPENCLAW_LITELLM_MODEL": "primary",
    "OPENCLAW_LITELLM_BASE_URL": "baseUrl",
    "OPENCLAW_MCP_SERVERS": None,
    "OPENCLAW_LITELLM_PROVIDER": None,
    "OPENCLAW_CONFIG_FORM_PATHS": None,
}


def _forms() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})


def _config(sso: bool, litellm: bool, mcp: bool) -> dict:
    application = {
        "mcp": {"enabled": mcp},
        "services": {
            "openclaw": {"config": SAMPLE, "mcp_servers": {"selected": [SERVER]}},
            "sso": {"enabled": sso},
            "litellm": {"enabled": litellm},
        },
    }
    return values("config", _forms(), application, {})


def _sinks(config: dict) -> dict:
    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    variables = {
        **declared,
        "OPENCLAW_CONFIG": config,
        "MCP_DISCOVERED_SERVERS": [DISCOVERED],
    }
    templar = Templar(loader=DataLoader(), variables=variables)
    return {
        name: templar.template(declared[name])
        for name, field in TEMPLATE_VARS.items()
        if field is None or field in config
    }


def _drift_read(held: dict, config: dict) -> dict:
    task_vars = next(
        task
        for task in DataLoader().load_from_file(str(TASKS), trusted_as_template=True)
        if str(task["name"]).startswith("📣 Report the managed")
    )["vars"]
    templar = Templar(
        loader=DataLoader(),
        variables={
            **task_vars,
            "openclaw_config_held": {"stdout": json.dumps(held)},
            "OPENCLAW_CONFIG": config,
        },
    )
    return templar.template(task_vars["forms_drift_current"])


def _rendered(sso: bool, litellm: bool, mcp: bool) -> tuple[dict, dict]:
    config = _config(sso, litellm, mcp)
    sinks = _sinks(config)
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters.update(McpFilterModule().filters())
    environment.filters.update({"to_json": json.dumps, "bool": bool})
    document = environment.from_string(read_text(str(TEMPLATE))).render(
        **sinks,
        OPENCLAW_TRUSTED_PROXY_ENABLED=sso,
        OPENCLAW_TRUSTED_PROXY_REQUIRED_HEADERS=["x-forwarded-user"],
        OPENCLAW_CONTROL_UI_ORIGINS=["https://claw.example.test"],
        OPENCLAW_LITELLM_ENABLED=litellm,
        OPENCLAW_LITELLM_API_KEY="sample-api-key-value",
    )
    return config, {"document": document, **sinks}


def _held(rendered: dict, managed: dict) -> dict:
    spec = importlib.util.spec_from_file_location("config_fields", READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = rendered["OPENCLAW_CONFIG_FORM_PATHS"]
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "openclaw.json"
        config.write_text(rendered["document"], encoding="utf-8")
        return module.fields(
            config, {field: path for field, path in paths.items() if field in managed}
        )


class TestManagedConfig(unittest.TestCase):
    def test_every_field_of_the_form_has_its_path_in_the_file(self) -> None:
        declared = load_yaml_any(str(VARS))["OPENCLAW_CONFIG_FORM_PATHS"]
        self.assertEqual(list(_forms()["config"]["fields"]), list(declared))

    def test_the_render_writes_every_managed_field_where_the_drift_reads_it(
        self,
    ) -> None:
        for sso in (True, False):
            for litellm in (True, False):
                for mcp in (True, False):
                    with self.subTest(sso=sso, litellm=litellm, mcp=mcp):
                        config, rendered = _rendered(sso, litellm, mcp)
                        self.assertEqual(
                            {"config": config},
                            _drift_read(_held(rendered, config), config),
                        )

    def test_the_auth_fields_follow_sso_and_the_model_fields_follow_litellm(
        self,
    ) -> None:
        self.assertEqual(["trustedProxies"], list(_config(False, False, False)))
        self.assertEqual(list(SAMPLE), list(_config(True, True, False)))
        self.assertEqual([*SAMPLE, "servers"], list(_config(True, True, True)))

    def test_the_rendered_server_carries_the_token_of_the_task_time_discovery(
        self,
    ) -> None:
        _config_values, rendered = _rendered(False, False, True)
        server = json.loads(rendered["document"])["mcp"]["servers"]["web-app-gitea"]
        self.assertEqual(f"Bearer {TOKEN}", server["headers"]["Authorization"])

    def test_the_drift_read_takes_only_the_urls_out_of_the_file(self) -> None:
        config, rendered = _rendered(False, False, True)
        held = _held(rendered, config)
        self.assertEqual({"web-app-gitea": SERVER["url"]}, held["servers"])
        self.assertNotIn(TOKEN, json.dumps(held))

    def test_the_drift_read_sees_a_moved_and_a_hand_added_server(self) -> None:
        config = _config(False, False, True)
        held = {
            "trustedProxies": SAMPLE["trustedProxies"],
            "servers": {"web-app-gitea": "http://moved/mcp", "manual": "http://x/mcp"},
        }
        self.assertEqual(
            [
                {**SERVER, "url": "http://moved/mcp"},
                {"id": "manual", "url": "http://x/mcp"},
            ],
            _drift_read(held, config)["config"]["servers"],
        )

    def test_the_provider_block_carries_the_model_of_the_managed_primary(
        self,
    ) -> None:
        _config_values, rendered = _rendered(True, True, False)
        provider = json.loads(rendered["document"])["models"]["providers"]
        self.assertEqual(
            [{"id": "sample-model", "name": "sample-model"}],
            provider[rendered["OPENCLAW_LITELLM_PROVIDER"]]["models"],
        )

    def test_the_computed_primary_names_the_provider_of_the_config(self) -> None:
        declared = DataLoader().load_from_file(
            str(ROLE / ROLE_FILE_META_SERVICES), trusted_as_template=True
        )
        primary = Templar(
            loader=DataLoader(), variables={"LITELLM_CHAT_MODEL": "chat"}
        ).template(declared["openclaw"]["config"]["primary"])
        provider = load_yaml_any(str(VARS))["OPENCLAW_LITELLM_PROVIDER"]
        self.assertEqual(f"{provider}/chat", primary)

    def test_the_drift_is_reported_before_the_render(self) -> None:
        names = [task["name"] for task in load_yaml_any(str(TASKS))]
        read = next(i for i, name in enumerate(names) if "Read the managed" in name)
        report = next(i for i, name in enumerate(names) if "Report the managed" in name)
        render = next(
            i for i, name in enumerate(names) if "Render the OpenClaw" in name
        )
        self.assertLess(read, report)
        self.assertLess(report, render)


if __name__ == "__main__":
    unittest.main()
