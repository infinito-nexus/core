"""Lint: env-file templates (``*env.j2``) must not pad ``KEY=value`` with
whitespace around the ``=`` or trailing whitespace.

Docker env-files take everything after ``=`` literally, so cosmetic column
alignment (``MYSQL_USER=     {{ ... }}``) leaks the spaces into the value and
breaks the app at runtime (e.g. MariaDB "Access denied for user '     friendica'").
Each assignment must be exactly ``KEY=value`` -- no space before/after ``=`` and
no trailing whitespace.

Scans every ``*env.j2`` under roles/. Jinja control lines (``{% %}``/``{# #}``)
and comments (``#``) are ignored. Mark a real exception with
``# nocheck: env-whitespace`` (or ``{# nocheck: env-whitespace #}``) above the line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "env-whitespace"

_ASSIGN_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<pre>[ \t]*)=(?P<post>[ \t]*)"
)


def _scan_file(path: Path) -> list[str]:
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    out: list[str] = []
    for idx, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith(("{", "#")):
            continue
        m = _ASSIGN_RE.match(line)
        problems = []
        if m:
            if m.group("pre"):
                problems.append("space before '='")
            if m.group("post"):
                problems.append("space after '=' (leaks into the value)")
        if line.rstrip() != line:
            problems.append("trailing whitespace")
        if problems and not is_suppressed_at(lines, idx, _RULE, mode="same-or-above"):
            out.append(f"line {idx}: {', '.join(problems)}: {line.rstrip()!r}")
    return out


class TestEnvJ2NoValueWhitespace(unittest.TestCase):
    def test_env_templates_have_no_value_whitespace(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for abs_path in iter_project_files(extensions=(".j2",)):
            p = Path(abs_path)
            if not p.name.endswith("env.j2"):
                continue
            issues = _scan_file(p)
            if issues:
                offenders[p] = issues

        if offenders:
            lines = [
                f"{sum(len(v) for v in offenders.values())} env.j2 line(s) pad "
                "KEY=value with whitespace (it becomes part of the value in a "
                "docker env-file):",
            ]
            for path, issues in sorted(offenders.items()):
                lines.append(f"  - {path.relative_to(PROJECT_ROOT)}:")
                lines.extend(f"      * {i}" for i in issues)
            lines.append("")
            lines.append(
                "Fix: write exactly KEY=value (no alignment spaces, no trailing whitespace)."
            )
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
