"""Lint guard: every Ansible ``rails runner`` invocation MUST source its
Ruby from an external ``.rb`` file via a ``file`` lookup fed over STDIN,
never inline Ruby embedded in the ``.yml`` task.

Background
==========
Embedding Ruby directly in a task — either as ``rails runner "<ruby>"``
inside a ``shell:``/``command:`` string, or as a ``stdin: |`` literal
block — forces fragile multi-level shell+YAML+Ruby quoting and makes the
Ruby invisible to Ruby tooling (syntax checks, formatters, reviews). The
project convention (see ``roles/web-app-decidim/tasks/01_setup.yml`` and
``roles/web-app-bigbluebutton/tasks/03_administrator.yml``) is to keep
the Ruby in ``roles/<role>/files/ruby/<name>.rb`` and feed it via::

    ansible.builtin.command:
      argv: [container, exec, -i, -e, "VAR={{ ... }}", "{{ CONTAINER }}",
             bash, -lc, "cd /app && bundle exec rails runner -"]
      stdin: "{{ lookup('file', 'ruby/<name>.rb') }}"

with parameters passed through the container environment (``-e``) and the
``.rb`` reading them via ``ENV.fetch(...)``.

Detection
=========
Scans every ``.yml`` / ``.yaml`` under ``roles/`` and ``tasks/``. For
each task block that invokes ``rails runner``, the block is COMPLIANT
only if it also feeds the runner from a ``file`` lookup of a ``.rb``
file (``lookup('file', 'ruby/x.rb')`` or
``lookup('ansible.builtin.file', ... '.rb')``). Otherwise the inline
Ruby is flagged.

Per-task opt-out: add ``# nocheck: rails-runner-inline`` (case
insensitive) anywhere inside the offending task block. The marker
grammar matches the project ``nocheck`` convention documented at
``docs/contributing/actions/testing/suppression.md``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

_SCAN_DIRS: frozenset[str] = frozenset({"roles", "tasks"})

_RAILS_RUNNER_RE = re.compile(r"rails\s+runner")
# A `file` lookup of a .rb script (the compliant Ruby source).
_FILE_LOOKUP_RE = re.compile(
    r"lookup\(\s*['\"](?:ansible\.(?:builtin|legacy)\.)?file['\"]",
)
_NOCHECK_RE = re.compile(
    r"nocheck\s*:\s*([a-z0-9][a-z0-9\-]*(?:\s*,\s*[a-z0-9][a-z0-9\-]*)*)",
    re.IGNORECASE,
)
_NOCHECK_KEY = "rails-runner-inline"
_LIST_ITEM_RE = re.compile(r"^(\s*)-\s")


def _task_indent(lines: list[str]) -> int:
    """Indentation (column) of the top-level task list items — the
    smallest indent at which a ``- `` list item appears. Deeper ``- ``
    lines (argv entries, nested data) are not task boundaries."""
    indents = [len(m.group(1)) for line in lines if (m := _LIST_ITEM_RE.match(line))]
    return min(indents) if indents else 0


def _enclosing_block(lines: list[str], idx: int, task_indent: int) -> tuple[int, int]:
    """Return ``[start, end)`` line indices of the task block containing
    line ``idx``: from its own top-level ``- `` item down to (but not
    including) the next one."""
    start = 0
    for i in range(idx, -1, -1):
        m = _LIST_ITEM_RE.match(lines[i])
        if m and len(m.group(1)) == task_indent:
            start = i
            break
    end = len(lines)
    for i in range(idx + 1, len(lines)):
        m = _LIST_ITEM_RE.match(lines[i])
        if m and len(m.group(1)) == task_indent:
            end = i
            break
    return start, end


def _block_name(lines: list[str], start: int, end: int) -> str:
    for i in range(start, end):
        stripped = lines[i].strip()
        if stripped.startswith(("- name:", "name:")):
            return stripped.split(":", 1)[1].strip().strip("\"'") or "<unnamed>"
    return "<unnamed>"


def _block_suppressed(block_text: str) -> bool:
    for match in _NOCHECK_RE.finditer(block_text):
        rules = {r.strip().lower() for r in match.group(1).split(",")}
        if _NOCHECK_KEY in rules:
            return True
    return False


def _file_offenders(path: Path) -> list[str]:
    try:
        src = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    if not _RAILS_RUNNER_RE.search(src):
        return []

    lines = src.splitlines()
    indent = _task_indent(lines)
    seen_blocks: set[tuple[int, int]] = set()
    offenders: list[str] = []

    for idx, line in enumerate(lines):
        match = _RAILS_RUNNER_RE.search(line)
        if not match:
            continue
        hash_pos = line.find("#")
        if 0 <= hash_pos < match.start():
            continue
        block = _enclosing_block(lines, idx, indent)
        if block in seen_blocks:
            continue
        seen_blocks.add(block)
        start, end = block
        block_text = "\n".join(lines[start:end])
        if _FILE_LOOKUP_RE.search(block_text) and ".rb" in block_text:
            continue
        if _block_suppressed(block_text):
            continue
        offenders.append(f"line {idx + 1}: task '{_block_name(lines, start, end)}'")
    return offenders


def _scan_paths() -> list[Path]:
    out: list[Path] = []
    for s in iter_project_files(extensions=(".yml", ".yaml"), exclude_tests=True):
        p = Path(s)
        try:
            rel = p.relative_to(PROJECT_ROOT)
        except ValueError:
            continue
        if not rel.parts or rel.parts[0] not in _SCAN_DIRS:
            continue
        out.append(p)
    return sorted(out)


class TestNoInlineRailsRunner(unittest.TestCase):
    """`rails runner` Ruby MUST live in a .rb file fed via a file lookup."""

    def test_no_inline_rails_runner(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _scan_paths():
            issues = _file_offenders(path)
            if issues:
                offenders[path] = issues

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [
            f"{len(offenders)} task file(s) invoke `rails runner` with inline "
            f"Ruby instead of an external .rb fed via a file lookup:",
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            lines.extend(f"      * {issue}" for issue in issues)
        lines.append("")
        lines.append(
            "Fix: move the Ruby into roles/<role>/files/ruby/<name>.rb (reading "
            "parameters via ENV.fetch), then run it with `bundle exec rails runner -` "
            "and `stdin: \"{{ lookup('file', 'ruby/<name>.rb') }}\"`, passing "
            "parameters through the container env (-e VAR=...). See "
            "roles/web-app-decidim/tasks/01_setup.yml for the pattern, or add "
            "`# nocheck: rails-runner-inline` inside the task with a rationale."
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
