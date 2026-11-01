"""Lint: every CVE suppression in a role's ``meta/services.yml`` is justified and dated.

An entry under ``<service>.security.suppressions`` needs ``id: CVE-YYYY-NNNN``,
an ``until: YYYY-MM-DD`` that has not passed, and a ``# nocheck: cve <reason>``
marker on the line directly above it::

    checkmk:
      security:
        suppressions:
          # nocheck: cve the vulnerable module is not loaded by the site
          - id: CVE-2026-1234
            until: 2026-12-31
"""

from __future__ import annotations

import datetime as dt
import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.security.suppressions import RULE, SuppressionError, parse_entries

from . import PROJECT_ROOT

MARKER = re.compile(rf"^\s*#\s*nocheck:\s*{RULE}\b(?P<reason>.*)$", re.IGNORECASE)
BLOCK = re.compile(r"^(?P<indent>\s*)suppressions:\s*$")
ENTRY = re.compile(r"^(?P<indent>\s*)-\s+\S")
REASON_SEPARATORS = " \t-:"


def _entry_lines(lines: list[str]) -> list[int]:
    """Return the index of every list item inside a ``suppressions:`` block."""
    found = []
    block_indent = None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if (
            block_indent is not None
            and indent <= block_indent
            and not line.lstrip().startswith(("-", "#"))
        ):
            block_indent = None
        match = BLOCK.match(line)
        if match:
            block_indent = len(match.group("indent"))
            continue
        if block_indent is not None and ENTRY.match(line):
            found.append(index)
    return found


def _marker_problem(lines: list[str], index: int) -> str | None:
    match = MARKER.match(lines[index - 1]) if index > 0 else None
    if match is None:
        return "has no # nocheck: cve <reason> marker directly above it"
    if not match.group("reason").strip(REASON_SEPARATORS):
        return "its # nocheck: cve marker gives no reason"
    return None


def problems(text: str, where: str, today: dt.date) -> list[str]:
    """Return every rule one ``meta/services.yml`` breaks.

    Args:
        text: the file content.
        where: the file name for the messages.
        today: the day an ``until`` must not lie before.
    """
    found = []
    lines = text.splitlines()
    for index in _entry_lines(lines):
        problem = _marker_problem(lines, index)
        if problem:
            found.append(f"{where}:{index + 1}: suppression {problem}")
    services = load_yaml_str(text) or {}
    if not isinstance(services, dict):
        return found
    for service, spec in services.items():
        if not isinstance(spec, dict) or "security" not in spec:
            continue
        security = spec["security"]
        entries = security.get("suppressions") if isinstance(security, dict) else None
        if not isinstance(entries, list):
            found.append(f"{where}: {service}.security must hold a suppressions list")
            continue
        for entry in entries:
            try:
                parsed = parse_entries([entry], f"{where}: {service}")[0]
            except SuppressionError as exc:
                found.append(str(exc))
                continue
            if parsed.until < today:
                found.append(
                    f"{where}: {service} suppression of {parsed.id} expired on {parsed.until}"
                )
    return found


class TestCveSuppressions(unittest.TestCase):
    def test_every_suppression_is_justified_and_dated(self) -> None:
        today = dt.datetime.now(tz=dt.UTC).date()
        found = []
        for path in sorted(
            (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
        ):
            text = read_text(str(path))
            if "suppressions:" in text:
                found += problems(text, str(path.relative_to(PROJECT_ROOT)), today)
        self.assertEqual(found, [], "\n".join(found))


TODAY = dt.date(2026, 10, 31)
VALID = """\
app:
  image: app
  security:
    suppressions:
      # nocheck: cve the module is not built into the image
      - id: CVE-2026-1234
        until: 2026-12-31
"""


class TestCheckerCases(unittest.TestCase):
    def _problems(self, text: str) -> list[str]:
        return problems(text, f"roles/r/{ROLE_FILE_META_SERVICES}", TODAY)

    def test_a_justified_dated_entry_passes(self) -> None:
        self.assertEqual(self._problems(VALID), [])

    def test_an_entry_without_a_marker_fails(self) -> None:
        text = VALID.replace(
            "      # nocheck: cve the module is not built into the image\n", ""
        )
        self.assertIn("has no # nocheck: cve <reason> marker", self._problems(text)[0])

    def test_a_marker_without_a_reason_fails(self) -> None:
        text = VALID.replace("cve the module is not built into the image", "cve")
        self.assertIn("gives no reason", self._problems(text)[0])

    def test_a_malformed_id_fails(self) -> None:
        text = VALID.replace("CVE-2026-1234", "CVE-26-1")
        self.assertIn("is no CVE-YYYY-NNNN id", self._problems(text)[0])

    def test_a_missing_until_fails(self) -> None:
        text = VALID.replace("        until: 2026-12-31\n", "")
        self.assertIn("until is required", self._problems(text)[0])

    def test_a_past_until_fails(self) -> None:
        text = VALID.replace("2026-12-31", "2026-10-30")
        self.assertIn("expired on 2026-10-30", self._problems(text)[0])

    def test_an_unmarked_entry_that_starts_with_until_fails(self) -> None:
        text = VALID.replace(
            "      # nocheck: cve the module is not built into the image\n"
            "      - id: CVE-2026-1234\n"
            "        until: 2026-12-31\n",
            "      - until: 2026-12-31\n        id: CVE-2026-1234\n",
        )
        self.assertIn("has no # nocheck: cve <reason> marker", self._problems(text)[0])

    def test_a_marker_for_another_rule_does_not_count(self) -> None:
        text = VALID.replace("nocheck: cve", "nocheck: url")
        self.assertIn("has no # nocheck: cve <reason> marker", self._problems(text)[0])


if __name__ == "__main__":
    unittest.main()
