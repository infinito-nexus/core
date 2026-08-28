"""The audit files a role under the classification the role itself declares.

``meta/mcp.yml`` carries a ``classification`` and the requirement's audit carries
a list per classification. Nothing tied them together, so a role kept its old
audit entry after it was implemented: twenty-four roles shipped a working MCP
surface while the audit still filed nine of them as untried adapter candidates
and two as having no path at all. Both statements looked authoritative and only
one was true.

The list a role belongs to is therefore derived from the role, not from the
prose: the audit's section titles are the classification vocabulary, and a role
that declares ``classification: adapter_server`` must appear under
``adapter_server`` and nowhere else.

Roles without ``meta/mcp.yml`` are out of scope here — that they appear
somewhere at all is what ``test_mcp_audit_completeness.py`` guards.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-audit-classification`` in the head of the role's
  ``meta/mcp.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT
from .test_mcp_audit_completeness import _audit_lists

_RULE = "mcp-audit-classification"

CLASSIFICATIONS = frozenset(
    {
        "native_server",
        "native_client",
        "native_both",
        "plugin_server",
        "sidecar_server",
        "adapter_server",
        "adapter_candidate",
        "blocked",
        "enabler",
        "subordinate",
        "no_surface",
    }
)


def _declared() -> dict[str, str]:
    """Return ``{application_id: classification}`` for every role declaring one."""
    declared: dict[str, str] = {}
    for mcp_path in sorted(Path(PROJECT_ROOT, "roles").glob(f"*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(mcp_path), default_if_missing={})
        if not isinstance(mcp, Mapping):
            continue
        classification = str(mcp.get("classification") or "").strip()
        if not classification:
            continue
        if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
            continue
        role_vars = load_yaml_any(
            str(mcp_path.parent.parent / ROLE_FILE_VARS_MAIN), default_if_missing={}
        )
        application_id = (role_vars or {}).get("application_id")
        if isinstance(application_id, str) and "{{" not in application_id:
            declared[application_id] = classification
    return declared


def _audit_placement() -> dict[str, str]:
    """Return ``{application_id: audit list title without its count}``."""
    placement: dict[str, str] = {}
    for title, ids in _audit_lists().items():
        name = title.rsplit(" (", 1)[0]
        for application_id in ids:
            placement[application_id] = name
    return placement


class TestMcpAuditClassification(unittest.TestCase):
    def test_every_declared_classification_is_known(self) -> None:
        unknown = sorted(
            f"{app}: {classification}"
            for app, classification in _declared().items()
            if classification not in CLASSIFICATIONS
        )
        self.assertEqual(
            [],
            unknown,
            f"role(s) declaring a classification outside {sorted(CLASSIFICATIONS)}:\n"
            + "\n".join(f"  - {u}" for u in unknown),
        )

    def test_the_audit_files_each_role_under_its_own_classification(self) -> None:
        placement = _audit_placement()
        mismatched = []
        for app, classification in sorted(_declared().items()):
            where = placement.get(app)
            if where is None:
                mismatched.append(
                    f"{app}: declares '{classification}' but appears in no audit list"
                )
            elif where != classification:
                mismatched.append(
                    f"{app}: declares '{classification}' but the audit files it "
                    f"under '{where}'"
                )
        self.assertEqual(
            [],
            mismatched,
            f"role(s) whose audit entry contradicts their own metadata "
            f"({len(mismatched)}):\n" + "\n".join(f"  - {m}" for m in mismatched),
        )

    def test_the_scan_finds_declared_classifications(self) -> None:
        self.assertTrue(
            _declared(),
            "no role declares an MCP classification, so the rule would pass "
            "vacuously; check that the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()
