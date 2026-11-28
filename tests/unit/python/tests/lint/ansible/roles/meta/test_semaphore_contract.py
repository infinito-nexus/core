"""Negative controls for the Semaphore contract lint."""

from __future__ import annotations

import unittest

from tests.lint.ansible.roles.meta import ROLES_DIR
from tests.lint.ansible.roles.meta import test_semaphore_contract as lint
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.required_by_coverage import role_is_invokable

LEAF = "web-app-fixture"
CUSTOM = "web-app-cst-fixture"
OBSERVED = "web-app-chess"
MARKER = f"# nocheck: {lint.RULE}  shared provider other roles consume"

VALID = """---
fixture:
  image: fixture
semaphore:
  bond: 0.5
  enabled: "{{ 'web-app-semaphore' in group_names }}"
  shared: "{{ 'web-app-semaphore' in group_names }}"
  control: true
  status: started
"""


def without_entry(text: str) -> str:
    """*text* with the ``semaphore`` entry and the comment block above it cut.

    Args:
        text: a services file's content.
    """
    lines = text.splitlines()
    span = lint.entry_span(lines)
    if span is None:
        return text
    start = span.start - 1
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    return "\n".join(lines[:start] + lines[span.stop - 1 :]) + "\n"


class TestSemaphoreContractFixtures(unittest.TestCase):
    def test_a_valid_entry_passes(self) -> None:
        self.assertEqual([], lint.entry_findings(LEAF, VALID))

    def test_a_removed_entry_fails(self) -> None:
        findings = lint.entry_findings(LEAF, without_entry(VALID))
        self.assertEqual(1, len(findings))
        self.assertIn("lacks the `semaphore` entry", findings[0])

    def test_the_missing_entry_finding_prints_a_block_that_passes(self) -> None:
        finding = lint.entry_findings(CUSTOM, without_entry(VALID))[0]
        self.assertIn("roles/web-app-cst-*", finding)
        self.assertIn(lint.ENTRY, finding.replace("\n      ", "\n"))
        self.assertEqual(
            [], lint.entry_findings(CUSTOM, f"{without_entry(VALID)}{lint.ENTRY}\n")
        )

    def test_a_custom_role_is_in_scope(self) -> None:
        self.assertTrue(role_is_invokable(CUSTOM))

    def test_a_paused_status_fails(self) -> None:
        text = VALID.replace("status: started", "status: paused")
        findings = lint.entry_findings(LEAF, text)
        self.assertEqual(1, len(findings))
        self.assertIn("status is 'paused'", findings[0])

    def test_a_quoted_control_fails(self) -> None:
        text = VALID.replace("control: true", 'control: "true"')
        findings = lint.entry_findings(LEAF, text)
        self.assertEqual(1, len(findings))
        self.assertIn("not a literal boolean", findings[0])

    def test_a_static_flag_fails(self) -> None:
        text = VALID.replace(
            "enabled: \"{{ 'web-app-semaphore' in group_names }}\"", "enabled: true"
        )
        findings = lint.entry_findings(LEAF, text)
        self.assertEqual(1, len(findings))
        self.assertIn("semaphore.enabled is True", findings[0])

    def test_a_missing_key_fails(self) -> None:
        text = VALID.replace("  status: started\n", "")
        self.assertIn(
            f"roles/{LEAF}/{ROLE_FILE_META_SERVICES}: `semaphore` lacks `status`",
            lint.entry_findings(LEAF, text),
        )

    def test_control_false_needs_a_reason(self) -> None:
        bare = VALID.replace("control: true", "control: false")
        self.assertEqual(1, len(lint.entry_findings(LEAF, bare)))
        short = VALID.replace(
            "control: true", f"control: false # nocheck: {lint.RULE} no"
        )
        self.assertEqual(1, len(lint.entry_findings(LEAF, short)))
        reasoned = VALID.replace("control: true", f"control: false {MARKER}")
        self.assertEqual([], lint.entry_findings(LEAF, reasoned))

    def test_an_entry_level_reason_covers_the_status(self) -> None:
        text = VALID.replace("semaphore:", f"{MARKER}\nsemaphore:").replace(
            "status: started", "status: paused"
        )
        self.assertEqual([], lint.entry_findings(LEAF, text))

    def test_the_control_plane_cannot_opt_in(self) -> None:
        text = VALID.replace("semaphore:", f"{MARKER}\nsemaphore:")
        findings = lint.entry_findings("web-app-keycloak", text)
        self.assertIn("must declare `control: false`", " ".join(findings))
        self.assertIn("must declare `enabled: false`", " ".join(findings))


class TestSemaphoreContractObserved(unittest.TestCase):
    def setUp(self) -> None:
        self.text = read_text(str(ROLES_DIR / OBSERVED / ROLE_FILE_META_SERVICES))

    def test_the_role_keeps_the_contract(self) -> None:
        self.assertEqual([], lint.entry_findings(OBSERVED, self.text))

    def test_the_role_fails_with_the_entry_removed(self) -> None:
        findings = lint.entry_findings(OBSERVED, without_entry(self.text))
        self.assertEqual(1, len(findings))
        self.assertIn("lacks the `semaphore` entry", findings[0])

    def test_the_role_fails_with_status_paused(self) -> None:
        text = self.text.replace("  status: started", "  status: paused")
        findings = lint.entry_findings(OBSERVED, text)
        self.assertEqual(1, len(findings))
        self.assertIn("status is 'paused'", findings[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
