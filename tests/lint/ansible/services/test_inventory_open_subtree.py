"""Lint: every ``# nocheck: inventory-open-subtree`` marker opens a mapping and says why.

The inventory validator accepts any child key the inventory sets under a
marked ``meta/services.yml`` key. A marker on no key, inside a list, on a
scalar, or without a reason of at least ``MIN_REASON_CHARS`` characters
opens nothing, so it is refused here instead of looking like it works.
"""

from __future__ import annotations

import unittest

from cli.administration.inventory.validate.open_subtrees import (
    LIST_SEGMENT,
    MIN_REASON_CHARS,
    RULE,
    markers,
)
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.meta.scan import iter_role_dirs
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _value_at(services, path: str):
    node = {"services": services}
    for segment in path.split("."):
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    return node


def findings_for(rel: str, text: str, services) -> list[str]:
    """Return one finding per misplaced or unreasoned marker.

    Args:
        rel: repository-relative path used in the findings.
        text: the ``meta/services.yml`` content.
        services: the same content, parsed.

    Returns:
        Human-readable findings, empty when every marker is valid.
    """
    found: list[str] = []
    for number, path, reason in markers(text.splitlines()):
        at = f"{rel}:{number}"
        if not path or LIST_SEGMENT in path:
            found.append(f"{at}: the marker sits on no mapping key outside a list")
        elif not isinstance(_value_at(services, path), dict):
            found.append(f"{at}: {path} is no mapping, so it has no children to open")
        if len(reason) < MIN_REASON_CHARS:
            found.append(
                f"{at}: `# nocheck: {RULE}` needs a reason of at least "
                f"{MIN_REASON_CHARS} characters"
            )
    return found


def _findings(text: str) -> list[str]:
    return findings_for("services.yml", text, load_yaml_str(text))


class TestInventoryOpenSubtree(unittest.TestCase):
    def test_every_marker_opens_a_mapping_and_states_a_reason(self):
        findings: list[str] = []
        for role_dir in iter_role_dirs():
            path = role_dir / ROLE_FILE_META_SERVICES
            if not path.is_file():
                continue
            text = read_text(str(path))
            if RULE not in text:
                continue
            findings.extend(
                findings_for(
                    f"roles/{role_dir.name}/{ROLE_FILE_META_SERVICES}",
                    text,
                    load_yaml_any(str(path), default_if_missing={}),
                )
            )
        if findings:
            self.fail(
                f"{len(findings)} `# nocheck: {RULE}` marker(s) open nothing:\n"
                + "\n".join(f"  - {finding}" for finding in findings)
            )

    def test_a_reasoned_marker_on_a_mapping_passes(self):
        text = f"wp:\n  options: # nocheck: {RULE}  the role validates each option\n    a: 1\n"
        self.assertEqual(_findings(text), [])

    def test_a_marker_without_a_reason_is_refused(self):
        findings = _findings(f"wp:\n  options: # nocheck: {RULE}\n    a: 1\n")
        self.assertEqual(len(findings), 1)
        self.assertIn("needs a reason", findings[0])

    def test_a_marker_on_a_scalar_is_refused(self):
        findings = _findings(f"wp:\n  title: x # nocheck: {RULE}  any value is fine\n")
        self.assertEqual(len(findings), 1)
        self.assertIn("is no mapping", findings[0])

    def test_a_marker_on_no_key_is_refused(self):
        findings = _findings(f"wp:\n  a: 1\n# nocheck: {RULE}  dangling marker text\n")
        self.assertEqual(len(findings), 1)
        self.assertIn("sits on no mapping key", findings[0])


if __name__ == "__main__":
    unittest.main()
