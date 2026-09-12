"""Every blocked role names what blocks it, and serves nothing meanwhile.

"Blocked" is the one disposition that can quietly mean two different things:
somebody looked and found a concrete obstacle, or nobody looked at all. Only a
named reason separates them, and only for as long as the reason stays attached
to the role rather than to a sentence covering the whole list.

The other half is the dangerous one. A role that declares a blocker while also
shipping an enabled MCP surface tells reviewers the path is shut and clients
the opposite, and the clients are right.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-blocked-reasons`` in the head of the role's ``meta/mcp.yml``.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT
from .test_mcp_audit_completeness import _audit_lists

_RULE = "mcp-blocked-reasons"
_REQUIREMENT = PROJECT_ROOT / "docs" / "requirements" / "035-mcp-proxy-expansion.md"
_BLOCKED = "blocked"

_REASON_ROW = re.compile(
    r"^\|\s*`(?P<role>[a-z0-9-]+)`\s*\|\s*`(?P<reason>[a-z_]+)`\s*\|\s*(?P<blocker>[^|]+?)\s*\|$"
)
_VOCABULARY = re.compile(
    r"^Allowed reasons MUST be documented and linted", re.MULTILINE
)


def _allowed_reasons() -> set[str]:
    """Return the reason tokens the requirement documents as allowed."""
    text = read_text(str(_REQUIREMENT))
    match = _VOCABULARY.search(text)
    if match is None:
        return set()
    line = text[match.start() : text.index("\n", match.start())]
    return set(re.findall(r"`([a-z_]+)`", line))


def _blocked_roles() -> list[str]:
    for title, ids in _audit_lists().items():
        if title.rsplit(" (", 1)[0] == _BLOCKED:
            return sorted(ids)
    return []


def _reason_rows() -> dict[str, str]:
    """Return ``{role: reason}`` for every row of the blocked reason table."""
    rows: dict[str, str] = {}
    for line in read_text(str(_REQUIREMENT)).splitlines():
        match = _REASON_ROW.match(line.strip())
        if match and match["blocker"].strip("- "):
            rows[match["role"]] = match["reason"]
    return rows


class TestMcpBlockedReasons(unittest.TestCase):
    def test_every_blocked_role_names_its_blocker(self) -> None:
        rows = _reason_rows()
        missing = [
            f"{role}: filed as blocked but the reason table carries no row, so "
            f"the entry cannot be told apart from one nobody reviewed"
            for role in _blocked_roles()
            if role not in rows
        ]
        self.assertEqual(
            [],
            missing,
            f"blocked role(s) without a named blocker ({len(missing)}):\n"
            + "\n".join(f"  - {m}" for m in missing),
        )

    def test_every_reason_comes_from_the_documented_vocabulary(self) -> None:
        allowed = _allowed_reasons()
        self.assertTrue(
            allowed,
            "the requirement no longer documents an allowed reason vocabulary, "
            "so this rule cannot check anything",
        )
        rows = _reason_rows()
        unknown = sorted(
            f"{role}: {reason}"
            for role, reason in rows.items()
            if role in set(_blocked_roles()) and reason not in allowed
        )
        self.assertEqual(
            [],
            unknown,
            f"blocked reason(s) outside the documented vocabulary "
            f"{sorted(allowed)}:\n" + "\n".join(f"  - {u}" for u in unknown),
        )

    def test_no_blocked_role_also_serves_a_surface(self) -> None:
        serving = []
        for role in _blocked_roles():
            mcp_path = PROJECT_ROOT / "roles" / role / ROLE_FILE_META_MCP
            if not mcp_path.is_file():
                continue
            if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
                continue
            mcp = load_yaml_any(str(mcp_path), default_if_missing={})
            if isinstance(mcp, Mapping) and mcp.get("enabled"):
                serving.append(
                    f"{role}: filed as blocked yet ships an enabled MCP surface; "
                    f"the audit says the path is shut and clients would find it open"
                )
        self.assertEqual(
            [],
            serving,
            "blocked role(s) serving anyway:\n"
            + "\n".join(f"  - {s}" for s in serving),
        )

    def test_the_scan_finds_blocked_roles(self) -> None:
        self.assertTrue(
            _blocked_roles(),
            "the audit lists no blocked role, so every rule here would pass "
            "vacuously; check that the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()
