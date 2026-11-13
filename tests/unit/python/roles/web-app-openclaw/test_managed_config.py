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
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles/web-app-openclaw"
TEMPLATE = ROLE / "templates/openclaw.json.j2"
VARS = ROLE / ROLE_FILE_VARS_MAIN
TASKS = ROLE / "tasks/utils/mcp.yml"
READER = ROLE / "files/python/config_fields.py"
SAMPLE = {
    "trustedProxies": ["198.51.100.0/24"],
    "mode": "sample-auth-mode",
    "userHeader": "x-sample-user",
    "primary": "litellm/sample-model",
    "baseUrl": "http://gateway.example.test/v1",
}
TEMPLATE_VARS = {
    "OPENCLAW_TRUSTED_PROXY_SOURCES": "trustedProxies",
    "OPENCLAW_TRUSTED_PROXY_MODE": "mode",
    "OPENCLAW_TRUSTED_PROXY_USER_HEADER": "userHeader",
    "OPENCLAW_LITELLM_PRIMARY": "primary",
    "OPENCLAW_LITELLM_MODEL": "primary",
    "OPENCLAW_LITELLM_BASE_URL": "baseUrl",
    "OPENCLAW_LITELLM_PROVIDER": None,
    "OPENCLAW_CONFIG_FORM_PATHS": None,
}


def _forms() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})


def _config(sso: bool, litellm: bool) -> dict:
    application = {
        "services": {
            "openclaw": {"config": SAMPLE},
            "sso": {"enabled": sso},
            "litellm": {"enabled": litellm},
        }
    }
    return values("config", _forms(), application, {})


def _sinks(config: dict) -> dict:
    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    variables = {**declared, "OPENCLAW_CONFIG": config}
    templar = Templar(loader=DataLoader(), variables=variables)
    return {
        name: templar.template(declared[name])
        for name, field in TEMPLATE_VARS.items()
        if field is None or field in config
    }


def _rendered(sso: bool, litellm: bool) -> tuple[dict, dict]:
    config = _config(sso, litellm)
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
        OPENCLAW_MCP_SERVERS=[],
    )
    return config, {"document": document, **sinks}


def _held(rendered: dict) -> dict:
    spec = importlib.util.spec_from_file_location("config_fields", READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "openclaw.json"
        config.write_text(rendered["document"], encoding="utf-8")
        return module.fields(config, rendered["OPENCLAW_CONFIG_FORM_PATHS"])


class TestManagedConfig(unittest.TestCase):
    def test_every_field_of_the_form_has_its_path_in_the_file(self) -> None:
        declared = load_yaml_any(str(VARS))["OPENCLAW_CONFIG_FORM_PATHS"]
        self.assertEqual(list(_forms()["config"]["fields"]), list(declared))

    def test_the_render_writes_every_managed_field_where_the_drift_reads_it(
        self,
    ) -> None:
        for sso in (True, False):
            for litellm in (True, False):
                with self.subTest(sso=sso, litellm=litellm):
                    config, rendered = _rendered(sso, litellm)
                    self.assertEqual(config, _held(rendered))

    def test_the_auth_fields_follow_sso_and_the_model_fields_follow_litellm(
        self,
    ) -> None:
        self.assertEqual(["trustedProxies"], list(_config(False, False)))
        self.assertEqual(list(SAMPLE), list(_config(True, True)))

    def test_the_provider_block_carries_the_model_of_the_managed_primary(
        self,
    ) -> None:
        _config_values, rendered = _rendered(True, True)
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
