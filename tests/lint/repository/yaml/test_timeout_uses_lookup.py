"""Lint guard: every ``timeout:`` in an Ansible task or handler must be scaled
through the ``timeout`` lookup, never a bare literal.

Background
==========
``lookup('timeout', <seconds>)`` multiplies the base by the global
``TIMEOUT_FACTOR`` (group_vars, default 1), so one knob stretches every wait in
the stack for a slow uplink. A hard-coded ``timeout: 3600`` opts that task out
of the knob and drifts silently.

Allowed
=======
* ``timeout: "{{ lookup('timeout', <base>) ... }}"`` (any filters after).
* Per-line opt-out via ``# nocheck: timeout-lookup`` for a genuinely fixed wait.

Scope
=====
Task and handler YAML under ``roles/*/tasks``, ``roles/*/handlers`` and the
top-level ``tasks/`` tree. ``meta/``, ``defaults/``, ``vars/``, ``files/`` and
Jinja templates are not task keywords and are skipped.
"""

from __future__ import annotations

import re
import unittest
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from utils.annotations.suppress import suppressed_line_numbers
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

if TYPE_CHECKING:
    from collections.abc import Iterable

_TIMEOUT_KEY_RE: re.Pattern[str] = re.compile(r"^\s*timeout:\s*(?P<value>\S.*?)\s*$")
_USES_LOOKUP_RE: re.Pattern[str] = re.compile(r"lookup\(\s*['\"]timeout['\"]")

_TASK_DIR_SEGMENTS = {"tasks", "handlers"}
_SKIP_DIR_SEGMENTS = {"files", "templates", "meta", "defaults", "vars"}


@lru_cache(maxsize=8192)
def _file_offenders(path: Path) -> tuple[str, ...]:
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return ()

    if "timeout:" not in text:
        return ()

    lines = text.splitlines()
    noqa_lines = suppressed_line_numbers(lines, "timeout-lookup")

    offenders: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if idx in noqa_lines:
            continue
        match = _TIMEOUT_KEY_RE.match(line)
        if not match:
            continue
        if _USES_LOOKUP_RE.search(match.group("value")):
            continue
        offenders.append(f"line {idx}: {line.strip()}")

    return tuple(offenders)


def _scan_paths() -> Iterable[Path]:
    for s in iter_project_files(exclude_tests=True, exclude_dirs=("docs",)):
        p = Path(s)
        if p.suffix not in (".yml", ".yaml"):
            continue
        parts = set(p.parts)
        if not (parts & _TASK_DIR_SEGMENTS):
            continue
        if parts & _SKIP_DIR_SEGMENTS:
            continue
        yield p


class TestTimeoutUsesLookup(unittest.TestCase):
    """A literal ``timeout:`` opts a task out of the global TIMEOUT_FACTOR knob."""

    def test_timeout_scaled_via_lookup(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _scan_paths():
            issues = list(_file_offenders(path))
            if issues:
                offenders[path] = issues

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [
            f"{len(offenders)} task/handler file(s) hard-code a timeout instead "
            f"of scaling it through lookup('timeout', <base>):",
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            lines.extend(f"      * {issue}" for issue in issues)
        lines.append("")
        lines.append(
            "Fix: timeout: \"{{ lookup('timeout', <base>) | int }}\" so the wait "
            "scales with TIMEOUT_FACTOR. A genuinely fixed wait may opt out with "
            "a trailing  # nocheck: timeout-lookup."
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
