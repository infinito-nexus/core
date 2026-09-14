"""``MCP_EXPECTED_TOOLS`` names the read probe each registered server declares.

The bridge spec asserts that a server serves the tool its ``meta/mcp.yml``
declares, and it learns which tool that is from this one env value. Rendered
wrong it does not fail: an empty map makes the spec skip the tool assertion for
every server and pass on the handshake alone, which is the weaker check it was
written to replace.

The block is extracted from the template rather than restated here, so a change
to the template is a change to what this test renders.
"""

from __future__ import annotations

import json
import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.applications import get_application_defaults
from utils.cache.files import PROJECT_ROOT, read_text

_TEMPLATE = PROJECT_ROOT / "roles/web-app-openwebui/templates/playwright.env.j2"
_BLOCK = re.compile(
    r"\{%\s*set _read_probes.*?^MCP_EXPECTED_TOOLS=.*?$",
    re.DOTALL | re.MULTILINE,
)
_SERVERS = ("web-app-gitea", "svc-db-qdrant", "web-svc-libretranslate")


def _render(server_ids: tuple[str, ...]) -> str:
    """Render the template's own read-probe block for the given servers."""
    block = _BLOCK.search(read_text(str(_TEMPLATE)))
    assert block, f"{_TEMPLATE} no longer carries the read-probe block"
    variables = {
        "applications": get_application_defaults(roles_dir=PROJECT_ROOT / "roles"),
        "OPENWEBUI_MCP_SERVERS": [
            {
                "id": server_id,
                "url": f"http://{server_id}:8080/mcp",
                "auth": "bearer_token",
                "token": "irrelevant-to-this-test",
            }
            for server_id in server_ids
        ],
    }
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(trust_as_template(block.group(0)))


def _rendered_map(server_ids: tuple[str, ...]) -> dict:
    """Return the map a spec reads, decoded the way the spec decodes it.

    ``dotenv_quote`` emits a quoted string with escaped inner quotes, which
    ``decodeDotenvQuotedValue`` (personas/utils/dotenv.js:17-30) unwraps with a
    JSON parse before the spec parses the payload itself. Decoding it once here
    would compare against a string that never reaches a spec.
    """
    line = _render(server_ids)
    _, _, value = line.partition("=")
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        value = json.loads(value)
    return json.loads(value)


class TestPlaywrightReadProbes(unittest.TestCase):
    def test_every_server_gets_the_tool_its_role_declares(self) -> None:
        rendered = _rendered_map(_SERVERS)
        expected = {
            server: (
                get_application_defaults(roles_dir=PROJECT_ROOT / "roles")[server]
                .get("mcp", {})
                .get("tools", {})
                .get("read_probe", {})
                .get("tool", "")
            )
            for server in _SERVERS
        }
        self.assertEqual(expected, rendered)

    def test_the_probes_are_non_empty_for_these_servers(self) -> None:
        self.assertEqual([], [k for k, v in _rendered_map(_SERVERS).items() if not v])

    def test_a_server_without_a_read_probe_renders_an_empty_string(self) -> None:
        self.assertEqual({"web-app-pretix": ""}, _rendered_map(("web-app-pretix",)))

    def test_no_discovered_server_renders_an_empty_map(self) -> None:
        self.assertEqual({}, _rendered_map(()))


if __name__ == "__main__":
    unittest.main()
