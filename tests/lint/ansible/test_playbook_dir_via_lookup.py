"""Lint: build absolute repo paths via the ``path_absolute`` lookup, never by
hand-joining ``playbook_dir``.

The ``path_absolute`` lookup (plugins/lookup/path_absolute.py) is the single
source for the repo-root anchor. Constructing a path from ``playbook_dir``
directly duplicates that anchor across the tree -- the exact redundancy the
lookup was added to remove. Three construction forms are forbidden in every
``.yml`` / ``.yaml`` / ``.j2`` file:

* ``[playbook_dir, '<rel>'] | path_join``   (list + path_join)
* ``playbook_dir ~ '/<rel>'``               (tilde concat)
* ``{{ playbook_dir }}/<rel>``              (raw interpolation)

A BARE ``playbook_dir`` passed as-is (e.g. ``discover_playwright_roles(
playbook_dir)``) is allowed; only path construction is flagged. Replace a hit
with ``lookup('path_absolute', '<rel>')`` (split variable segments across
terms, e.g. ``lookup('path_absolute', 'roles', application_id, 'x.j2')``).

Mark a genuine exception with ``# nocheck: path-absolute`` (YAML) or
``{# nocheck: path-absolute #}`` (Jinja), placed same-or-above the line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "path-absolute"
SCAN_SUFFIXES = (".yml", ".yaml", ".j2")

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("list-path_join", re.compile(r"\[\s*playbook_dir\s*,")),
    ("tilde-concat", re.compile(r"playbook_dir\s*~")),
    ("raw-interp", re.compile(r"playbook_dir\s*\}\}\s*/")),
)


def _scan_file(path: Path) -> list[str]:
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    offenders: list[str] = []
    for idx, line in enumerate(lines, start=1):
        for kind, pattern in _PATTERNS:
            if pattern.search(line) and not is_suppressed_at(
                lines, idx, _RULE, mode="same-or-above"
            ):
                offenders.append(f"line {idx}: [{kind}] {line.strip()}")
                break
    return offenders


class TestPlaybookDirViaLookup(unittest.TestCase):
    def test_no_manual_playbook_dir_path_construction(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for abs_path in iter_project_files(extensions=SCAN_SUFFIXES):
            issues = _scan_file(Path(abs_path))
            if issues:
                offenders[Path(abs_path)] = issues

        if not offenders:
            return

        lines = [
            f"{len(offenders)} file(s) build a repo path from `playbook_dir` "
            "by hand instead of the `path_absolute` lookup:",
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {path.relative_to(PROJECT_ROOT)}:")
            lines.extend(f"      * {issue}" for issue in issues)
        lines.append("")
        lines.append(
            "Fix: replace with `lookup('path_absolute', '<rel>')` "
            "(plugins/lookup/path_absolute.py) -- split variable segments into "
            "separate terms, e.g. "
            "`lookup('path_absolute', 'roles', application_id, 'templates/x.j2')`. "
            "Add `# nocheck: path-absolute` (YAML) / `{# nocheck: path-absolute #}` "
            "(Jinja) same-or-above for a documented exception."
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
