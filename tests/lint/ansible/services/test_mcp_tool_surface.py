"""The tool surface ``meta/mcp.yml`` declares matches the contract that ships.

The adapter derives what it serves from ``files/mcp/tools.json`` alone:
``policy.listed_tools`` is ``sorted(contract["tools"])`` and the rendered
contract carries no allowlist at all. Everything in ``meta/mcp.yml`` is
therefore a declaration that nothing recomputes - the same shape as the pinned
digests, which had silently drifted in ten of twelve roles before a check
existed. Reviewers, the requirement documents and the authorization metadata
read the declaration; the running adapter reads the file.

Three relations, deliberately not all equalities:

* ``tools.allowlist`` equals the shipped tool names. A name only in the
  declaration promises a tool no client can call; a name only in the file
  serves one the platform never approved.
* ``tools.writer_allowlist`` is a superset of the allowlist, never an equality:
  a writer surface names tools that cannot ship while mutations are off,
  because ``passthrough.py`` rejects the whole contract at load time as soon as
  one tool declares ``mutating: true`` against ``mutating_tools_enabled: false``.
* ``tools.upstream_serves``, where stated, contains the allowlist. Allowing a
  tool the upstream never offered fails at first use, not at deploy.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-tool-surface`` on, or directly above, the declaring line.
"""

from __future__ import annotations

import json
import unittest

from utils.annotations.suppress import is_suppressed_for_key
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

_RULE = "mcp-tool-surface"
_CONTRACT_RELATIVE = "files/mcp/tools.json"


def _names(value: object) -> set[str] | None:
    """Return the declared names, or ``None`` when the key is absent."""
    if not isinstance(value, list):
        return None
    return {str(item) for item in value}


def _shipped_tools(path) -> set[str]:
    """Return the tool names the contract file ships."""
    parsed = json.loads(read_text(str(path)))
    tools = parsed.get("tools", parsed) if isinstance(parsed, dict) else {}
    return set(tools) if isinstance(tools, dict) else set()


class TestMcpToolSurface(unittest.TestCase):
    def test_declared_surface_matches_the_shipped_contract(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        offenders: list[str] = []
        checked = 0
        for mcp_path in sorted(roles_root.glob(f"*/{ROLE_FILE_META_MCP}")):
            mcp = load_yaml_any(str(mcp_path), default_if_missing={}) or {}
            tools_block = mcp.get("tools")
            if not isinstance(tools_block, dict):
                continue

            role = mcp_path.parent.parent
            contract_path = role / _CONTRACT_RELATIVE
            allowlist = _names(tools_block.get("allowlist"))
            if allowlist is None or not contract_path.is_file():
                continue

            lines = read_text(str(mcp_path)).splitlines()
            shipped = _shipped_tools(contract_path)
            checked += 1

            if allowlist != shipped and not is_suppressed_for_key(
                lines, "allowlist", _RULE
            ):
                only_declared = sorted(allowlist - shipped)
                only_shipped = sorted(shipped - allowlist)
                offenders.append(
                    f"{role.name}: tools.allowlist and {_CONTRACT_RELATIVE} "
                    f"disagree; declared only {only_declared}, shipped only "
                    f"{only_shipped}"
                )

            writers = _names(tools_block.get("writer_allowlist"))
            if (
                writers is not None
                and not allowlist <= writers
                and not is_suppressed_for_key(lines, "writer_allowlist", _RULE)
            ):
                offenders.append(
                    f"{role.name}: tools.writer_allowlist omits "
                    f"{sorted(allowlist - writers)}, so a writer would reach "
                    f"less than a reader"
                )

            serves = _names(tools_block.get("upstream_serves"))
            if (
                serves is not None
                and not allowlist <= serves
                and not is_suppressed_for_key(lines, "upstream_serves", _RULE)
            ):
                offenders.append(
                    f"{role.name}: tools.allowlist names "
                    f"{sorted(allowlist - serves)}, which tools.upstream_serves "
                    f"does not report as offered"
                )

        self.assertEqual(
            [],
            offenders,
            f"declared tool surface diverges from the contract ({len(offenders)}):\n"
            + "\n".join(f"  - {o}" for o in offenders),
        )
        self.assertTrue(
            checked,
            "no role declares a tool allowlist next to a shipped contract, so "
            "the rule would pass vacuously; check that the scan still reads the "
            "right topic",
        )
