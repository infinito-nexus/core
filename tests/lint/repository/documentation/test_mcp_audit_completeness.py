"""The MCP audit must dispose of every role, exactly once.

The exhaustive audit in the MCP requirement is the record of what each role's
MCP surface is, including the roles that deliberately have none. A role missing
from it reads as "not yet looked at" and as "decided against" at the same time,
and nothing distinguishes the two. A role in two lists carries two dispositions.

Three checks, all derived from the repository rather than from the snapshot the
requirement was written against:

* every role whose ``vars/main.yml`` sets a literal ``application_id`` appears
  in the audit;
* no role appears in more than one audit list;
* the count each list declares in its heading matches the ids it carries, so a
  hand-edited list cannot silently drop an entry.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-audit-completeness`` in the head of the role's ``vars/main.yml``.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_RULE = "mcp-audit-completeness"
_REQUIREMENT = PROJECT_ROOT / "docs" / "requirements" / "035-mcp-proxy-expansion.md"
_AUDIT_HEADING = "## Exhaustive Application-ID Audit"

_SECTION_HEADING = re.compile(r"^###\s+(?P<title>.+?)\s+\((?P<count>\d+)\)\s*$")
_INLINE_LIST = re.compile(
    r"^\*\*`(?P<title>[^`]+)`\s+\((?P<count>\d+)\):\*\*\s+(?P<body>.+)$"
)
_ID_LIST = re.compile(r"^(`[a-z0-9-]+`)(,\s*`[a-z0-9-]+`)*\.$")
_ID = re.compile(r"`([a-z0-9-]+)`")


def _audit_lists() -> dict[str, list[str]]:
    """Return ``{list title: [application_id]}`` for every list in the audit.

    A list is a line made only of backticked ids, attributed either to its own
    ``**`reason` (n):**`` lead-in or to the nearest ``### Title (n)`` heading.
    Prose that merely mentions a backticked term is not a list and is ignored.
    """
    lines = read_text(str(_REQUIREMENT)).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == _AUDIT_HEADING)
    lists: dict[str, list[str]] = {}
    heading: tuple[str, int] | None = None

    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        section = _SECTION_HEADING.match(stripped)
        if section:
            heading = (section["title"], int(section["count"]))
            continue
        inline = _INLINE_LIST.match(stripped)
        if inline and _ID_LIST.match(inline["body"]):
            lists[f"{inline['title']} ({inline['count']})"] = _ID.findall(
                inline["body"]
            )
            continue
        if heading and _ID_LIST.match(stripped):
            lists[f"{heading[0]} ({heading[1]})"] = _ID.findall(stripped)
            heading = None
    return lists


def _declared_count(title: str) -> int:
    return int(title.rsplit("(", 1)[1].rstrip(")"))


def _literal_application_ids() -> set[str]:
    ids = set()
    for vars_file in sorted(PROJECT_ROOT.glob(f"roles/*/{ROLE_FILE_VARS_MAIN}")):
        data = load_yaml_any(str(vars_file), default_if_missing={})
        if not isinstance(data, dict):
            continue
        application_id = data.get("application_id")
        if not isinstance(application_id, str) or "{{" in application_id:
            continue
        if is_suppressed_in_head(read_text(str(vars_file)).splitlines(), _RULE):
            continue
        ids.add(application_id)
    return ids


class TestMcpAuditCompleteness(unittest.TestCase):
    def test_every_role_is_disposed_of(self) -> None:
        listed = {app for ids in _audit_lists().values() for app in ids}
        missing = sorted(_literal_application_ids() - listed)
        self.assertEqual(
            [],
            missing,
            f"roles absent from the MCP audit ({len(missing)}); absence is not a "
            f"disposition, so each needs a list in {_REQUIREMENT.name}:\n"
            + "\n".join(f"  - {app}" for app in missing),
        )

    def test_no_role_carries_two_dispositions(self) -> None:
        seen: dict[str, str] = {}
        clashes: list[str] = []
        for title, ids in _audit_lists().items():
            for app in ids:
                if app in seen:
                    clashes.append(f"{app}: {seen[app]} and {title}")
                seen[app] = title
        self.assertEqual(
            [],
            sorted(clashes),
            "application ids in more than one audit list:\n"
            + "\n".join(f"  - {clash}" for clash in sorted(clashes)),
        )

    def test_each_list_carries_the_count_it_declares(self) -> None:
        drift = [
            f"{title}: {len(ids)} ids"
            for title, ids in _audit_lists().items()
            if len(ids) != _declared_count(title)
        ]
        self.assertEqual(
            [],
            drift,
            "audit lists whose heading count disagrees with their entries:\n"
            + "\n".join(f"  - {entry}" for entry in drift),
        )


if __name__ == "__main__":
    unittest.main()
