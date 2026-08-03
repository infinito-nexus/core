"""Every ``MODE_*`` read in a truthiness position must carry ``| bool``.

Rationale
=========
The deploy CLI passes each mode to ansible-playbook as an extra-var. A
``key=value`` extra-var arrives as a **string** at the highest precedence,
so ``MODE_DEBUG=false`` is the non-empty, and therefore truthy, string
``"false"`` wherever the filter is missing. ``| bool`` maps it back, which
is why ``when: MODE_DEBUG | bool`` was always right and
``{{ 'restarted' if MODE_DEBUG else omit }}`` silently inverted.

Passing the modes as a JSON extra-var fixes the encoding, but a bare read
stays a trap: it makes the meaning of a flag depend on how its value
reached Ansible. Require the filter and the question never arises.

Per-line opt-out
================
Add ``# nocheck: mode-flag-filter`` on the same line or the line
immediately above, for a genuine string comparison such as
``when: MODE_RESET == 'hard'``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "mode-flag-filter"

_TRUTHINESS_READ = re.compile(
    r"(?:(?<=if )|(?<=not )|(?<=and )|(?<=or )|(?<=when: ))(MODE_[A-Z_]+)\b(?! *\| *)"
)

_SCAN_PREFIXES = ("roles/", "group_vars/", "tasks/", "inventories/")
_SCAN_EXTS = (".yml", ".yaml", ".j2")


def _is_scan_target(rel_path: str) -> bool:
    return rel_path.startswith(_SCAN_PREFIXES) and rel_path.endswith(_SCAN_EXTS)


class TestModeFlagsAreFiltered(unittest.TestCase):
    def test_every_mode_read_carries_the_bool_filter(self) -> None:
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(
            extensions=_SCAN_EXTS, exclude_tests=True
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            for line_no, line in enumerate(lines, start=1):
                if not _TRUTHINESS_READ.search(line):
                    continue
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, line_no, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(set(findings))
            )
            self.fail(
                "Found MODE_* flags read as a truthiness without `| bool`. An "
                "extra-var passed as `key=value` arrives as a string, so "
                "`MODE_DEBUG=false` is truthy at every such site.\n\n"
                "Fix: `{{ 'a' if MODE_DEBUG | bool else 'b' }}`, "
                "`when: MODE_ASSERT | bool`.\n\n"
                "Or add `# nocheck: mode-flag-filter` on the same line or the "
                "line above for a genuine string comparison.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
