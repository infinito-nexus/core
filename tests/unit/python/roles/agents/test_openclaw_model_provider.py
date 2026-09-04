"""OpenClaw refuses to boot on a model entry that misses a key.

The gateway validates its whole configuration before it serves anything, and
a rejected file is not a degraded start but a crash loop: OpenClaw retries,
trips its own restart breaker after four unclean boots, and the container
exits 128 while the deploy sits in the health check until it gives up.

The provider block reached the repository without ever being rendered in a
test - every case here passed OPENCLAW_LITELLM_ENABLED=False, so the block was
skipped and its shape was never checked against anything.
"""

from __future__ import annotations

import importlib.util
import json
import unittest

from jinja2 import Environment, FileSystemLoader

from . import PROJECT_ROOT

OPENCLAW = PROJECT_ROOT / "roles/web-app-openclaw/templates"
FILTERS = PROJECT_ROOT / "plugins/filter/mcp/authorization.py"

MODEL = "qwen2.5:0.5b"

CONTEXT = {
    "OPENCLAW_URL": "https://claw.example.org",
    "OPENCLAW_LITELLM_ENABLED": True,
    "OPENCLAW_LITELLM_PROVIDER": "litellm",
    "OPENCLAW_LITELLM_MODEL": MODEL,
    "OPENCLAW_LITELLM_BASE_URL": "http://litellm:4000/v1",
    "OPENCLAW_LITELLM_API_KEY": "sk-" + "x" * 20,
    "OPENCLAW_MCP_SERVERS": [],
}


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


def _render(**overrides) -> dict:
    """Return the gateway config as OpenClaw would parse it.

    Args:
        overrides: context values replacing the defaults.
    """
    env = Environment(loader=FileSystemLoader(str(OPENCLAW)), autoescape=False)  # noqa: S701 - renders configuration, not markup
    env.filters.update(_filters())
    return json.loads(
        env.get_template("openclaw.json.j2").render(**{**CONTEXT, **overrides})
    )


class TestOpenClawModelProvider(unittest.TestCase):
    def _entry(self, **overrides) -> dict:
        """Return the provider's single model entry.

        Args:
            overrides: context values replacing the defaults.
        """
        return _render(**overrides)["models"]["providers"]["litellm"]["models"][0]

    def test_the_model_entry_carries_both_keys_the_gateway_validates(self) -> None:
        self.assertEqual({"id": MODEL, "name": MODEL}, self._entry())

    def test_the_name_matches_the_id(self) -> None:
        """Which key reaches the API is the upstream's choice, not ours."""
        entry = self._entry()
        self.assertEqual(entry["id"], entry["name"])

    def test_the_primary_agent_model_names_the_same_provider(self) -> None:
        rendered = _render()
        self.assertEqual(
            f"litellm/{MODEL}",
            rendered["agents"]["defaults"]["model"]["primary"],
        )
        self.assertIn("litellm", rendered["models"]["providers"])

    def test_the_block_disappears_when_litellm_is_off(self) -> None:
        rendered = _render(OPENCLAW_LITELLM_ENABLED=False)
        self.assertNotIn("models", rendered)
        self.assertNotIn("agents", rendered)


if __name__ == "__main__":
    unittest.main()
