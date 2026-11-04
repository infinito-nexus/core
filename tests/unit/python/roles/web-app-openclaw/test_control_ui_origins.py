from __future__ import annotations

import json
import unittest

from jinja2 import Environment, StrictUndefined

from plugins.filter.mcp.authorization import FilterModule as McpFilterModule
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.domains.default_primary import default_domain_primary
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-openclaw"
PRIMARY = default_domain_primary()
NODE_ONION = "7csk6epqensl5eaw3rogyw2hhzusuahoj4n6iidgnrolgzq3muymrlyd.onion"
CLEARNET_URL = f"https://claw.ai.{PRIMARY}"
ONION_URL = f"http://claw.ai.{NODE_ONION}"


def _environment() -> Environment:
    env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders JSON and an ansible var expression, not markup
    env.filters.update(McpFilterModule().filters())
    env.filters.update({"to_json": json.dumps, "bool": bool})
    return env


def _allowed_origins(network_urls: list[str]) -> list[str]:
    """Return the origins the rendered gateway config admits to the Control UI.

    Args:
        network_urls: the answer of lookup('network_urls', OPENCLAW_URL) on the host.

    Returns:
        gateway.controlUi.allowedOrigins of the rendered openclaw.json.
    """

    def lookup(*terms: str) -> list[str]:
        if terms != ("network_urls", CLEARNET_URL):
            raise AssertionError(f"the origins render an unexpected lookup{terms}")
        return network_urls

    env = _environment()
    expression = load_yaml(ROLE / ROLE_FILE_VARS_MAIN)["OPENCLAW_CONTROL_UI_ORIGINS"]
    origins = env.compile_expression(
        expression.strip().removeprefix("{{").removesuffix("}}")
    )(lookup=lookup, OPENCLAW_URL=CLEARNET_URL)
    config = env.from_string(
        read_text(str(ROLE / "templates" / "openclaw.json.j2"))
    ).render(
        OPENCLAW_TRUSTED_PROXY_SOURCES=["192.168.0.0/16"],
        OPENCLAW_TRUSTED_PROXY_ENABLED=False,
        OPENCLAW_CONTROL_UI_ORIGINS=origins,
        OPENCLAW_LITELLM_ENABLED=False,
        OPENCLAW_MCP_SERVERS=[],
    )
    return json.loads(config)["gateway"]["controlUi"]["allowedOrigins"]


class TestControlUiOrigins(unittest.TestCase):
    def test_the_onion_sibling_of_the_gateway_is_an_allowed_origin(self) -> None:
        self.assertEqual(
            _allowed_origins([CLEARNET_URL, ONION_URL]),
            [CLEARNET_URL, ONION_URL],
            "a Tor browser presents the onion origin, and a gateway that admits "
            "only the clearnet one answers origin-not-allowed before the pairing step",
        )

    def test_a_host_served_on_one_network_admits_only_its_domain(self) -> None:
        self.assertEqual(_allowed_origins([CLEARNET_URL]), [CLEARNET_URL])


if __name__ == "__main__":
    unittest.main()
