"""The agent clients register only the tools their providers declare.

Both upstreams default to registering every tool an MCP server happens to
serve. Hermes says so in ``tools/mcp_tool.py``: "Neither set -> register all
tools (backward-compatible default)". OpenClaw's ``toolFilter`` is absent
unless written. A provider that grows a mutating tool would therefore reach
both agents without anyone declaring it, so the rendered configuration has to
carry the allowlist rather than rely on the default.

That holds for the empty allowlist too: a provider that declares none is the
case where the default is most dangerous, so the filter is rendered
unconditionally, the way ``web-app-n8n``'s client node pins ``include`` to
``selected`` whatever ``includeTools`` resolves to.
"""

from __future__ import annotations

import importlib.util
import json
import unittest

import yaml
from jinja2 import Environment, FileSystemLoader

from . import PROJECT_ROOT

HERMES = PROJECT_ROOT / "roles/web-app-hermes/templates"
OPENCLAW = PROJECT_ROOT / "roles/web-app-openclaw/templates"
FILTERS = PROJECT_ROOT / "plugins/filter/mcp/authorization.py"

SERVERS = [
    {
        "id": "svc-db-qdrant",
        "url": "http://qdrantmcp:8080/mcp",
        "token": "q" * 40,
        "auth": "bearer_token",
        "owner": "mcp-svc-db-qdrant",
        "tools": ["qdrant_list_collections", "qdrant_get_collection"],
        "transport": "streamable-http",
    },
    {
        "id": "web-app-prometheus",
        "url": "http://prometheusmcp:8080/mcp",
        "token": "p" * 40,
        "auth": "bearer_token",
        "owner": "mcp-web-app-prometheus",
        "tools": [],
        "mutating": [],
        "transport": "streamable-http",
    },
    {
        "id": "web-app-baserow",
        "url": "http://baserow:8080/mcp",
        "token": "b" * 40,
        "auth": "bearer_token",
        "owner": "mcp-web-app-baserow",
        "tools": ["list_databases", "list_tables", "create_rows", "delete_rows"],
        "mutating": ["create_rows", "delete_rows"],
        "transport": "streamable-http",
    },
]


def _filters() -> dict:
    spec = importlib.util.spec_from_file_location("mcp_authorization", FILTERS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "mcp_authorization": module.mcp_authorization,
        "mcp_renderable_servers": module.mcp_renderable_servers,
        "to_json": json.dumps,
        "bool": bool,
    }


def _yaml(text: str):
    """Parse a rendered template.

    Args:
        text: the rendered document.

    The project's YAML cache is keyed by path; this input never becomes a file.
    """
    return yaml.safe_load(text)  # nocheck: direct-yaml  a render, not a file


def _render(directory, name, **context) -> str:
    env = Environment(loader=FileSystemLoader(str(directory)), autoescape=False)  # noqa: S701 - renders configuration, not markup
    env.filters.update(_filters())
    return env.get_template(name).render(**context)


class TestAgentToolFilter(unittest.TestCase):
    def test_hermes_pins_the_declared_allowlist(self) -> None:
        rendered = _yaml(_render(HERMES, "config.yaml.j2", HERMES_MCP_SERVERS=SERVERS))
        entry = rendered["mcp_servers"]["svc_db_qdrant"]
        self.assertEqual(
            ["qdrant_list_collections", "qdrant_get_collection"],
            entry["tools"]["include"],
        )

    def test_hermes_pins_an_empty_allowlist_rather_than_omitting_it(self) -> None:
        rendered = _yaml(_render(HERMES, "config.yaml.j2", HERMES_MCP_SERVERS=SERVERS))
        entry = rendered["mcp_servers"]["web_app_prometheus"]
        self.assertEqual(
            [],
            entry["tools"]["include"],
            "omitting the key means 'register all tools' upstream, so a "
            "provider that declares no allowlist would reach the agent with "
            "every tool it happens to serve",
        )

    def test_openclaw_pins_the_declared_allowlist(self) -> None:
        rendered = json.loads(
            _render(
                OPENCLAW,
                "openclaw.json.j2",
                OPENCLAW_URL="https://claw.example.org",
                OPENCLAW_LITELLM_ENABLED=False,
                OPENCLAW_MCP_SERVERS=SERVERS,
            )
        )
        entry = rendered["mcp"]["servers"]["svc-db-qdrant"]
        self.assertEqual(
            ["qdrant_list_collections", "qdrant_get_collection"],
            entry["toolFilter"]["include"],
        )

    def test_openclaw_stays_valid_json_with_an_empty_filter(self) -> None:
        rendered = json.loads(
            _render(
                OPENCLAW,
                "openclaw.json.j2",
                OPENCLAW_URL="https://claw.example.org",
                OPENCLAW_LITELLM_ENABLED=False,
                OPENCLAW_MCP_SERVERS=SERVERS,
            )
        )
        self.assertEqual(
            [],
            rendered["mcp"]["servers"]["web-app-prometheus"]["toolFilter"]["include"],
        )
        self.assertEqual(
            {"svc-db-qdrant", "web-app-prometheus", "web-app-baserow"},
            set(rendered["mcp"]["servers"]),
        )

    def test_hermes_never_offers_a_tool_the_provider_calls_mutating(self) -> None:
        rendered = _yaml(_render(HERMES, "config.yaml.j2", HERMES_MCP_SERVERS=SERVERS))
        include = rendered["mcp_servers"]["web_app_baserow"]["tools"]["include"]
        self.assertEqual(["list_databases", "list_tables"], include)

    def test_openclaw_never_offers_a_tool_the_provider_calls_mutating(self) -> None:
        rendered = json.loads(
            _render(
                OPENCLAW,
                "openclaw.json.j2",
                OPENCLAW_URL="https://claw.example.org",
                OPENCLAW_LITELLM_ENABLED=False,
                OPENCLAW_MCP_SERVERS=SERVERS,
            )
        )
        entry = rendered["mcp"]["servers"]["web-app-baserow"]
        self.assertEqual(
            ["list_databases", "list_tables"], entry["toolFilter"]["include"]
        )

    def test_neither_agent_inlines_a_bearer_for_a_bearer_provider(self) -> None:
        hermes = _render(HERMES, "config.yaml.j2", HERMES_MCP_SERVERS=SERVERS)
        self.assertNotIn("q" * 40, hermes)


if __name__ == "__main__":
    unittest.main()
