"""Every MCP server role gates its surface on the role's MCP-enabled flag.

Without the gate a deployment that switches MCP off would still render the
endpoint, so the flag would document an intent the deployment does not honour.
"""

from __future__ import annotations

import unittest

from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.mcp import MCP_SERVER_DIRECTIONS
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"

GATE_MARKERS = ("MCP_ENABLED", "services.mcp.enabled")
SEARCHED_EXTENSIONS = (".yml", ".yaml", ".j2")
SERVICES_BASENAME = ROLE_FILE_META_SERVICES.split("/")[-1]


def _server_roles() -> list[str]:
    roles = []
    for role_dir in sorted(ROLES_DIR.iterdir()):
        services_path = role_dir / ROLE_FILE_META_SERVICES
        if not role_dir.is_dir() or not services_path.is_file():
            continue
        data = load_yaml_any(str(services_path))
        block = data.get("mcp") if isinstance(data, dict) else None
        if not isinstance(block, dict):
            continue
        if str(block.get("direction") or "") in MCP_SERVER_DIRECTIONS:
            roles.append(role_dir.name)
    return roles


def _roles_that_gate() -> set[str]:
    prefix = f"{ROLES_DIR}/"
    gating = set()
    for path, text in iter_project_files_with_content(
        extensions=SEARCHED_EXTENSIONS, exclude_tests=True
    ):
        if not path.startswith(prefix) or path.endswith(SERVICES_BASENAME):
            continue
        if any(marker in text for marker in GATE_MARKERS):
            gating.add(path[len(prefix) :].split("/", 1)[0])
    return gating


class TestMcpDisabledHasNoSurface(unittest.TestCase):
    def test_server_roles_exist(self) -> None:
        self.assertTrue(_server_roles(), "no role declares an MCP server surface")

    def test_every_server_role_gates_its_surface(self) -> None:
        gating = _roles_that_gate()
        ungated = [r for r in _server_roles() if r not in gating]
        self.assertEqual(
            ungated,
            [],
            "MCP server roles that render their surface unconditionally, so "
            f"`services.mcp.enabled=false` would not remove it: {ungated}",
        )


if __name__ == "__main__":
    unittest.main()
