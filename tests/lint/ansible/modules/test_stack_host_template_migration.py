"""Drift guard: every bare `template:` task must adopt the project's
:mod:`plugins.action.stack_host_template` wrapper or carry an explicit
`# nocheck: stack-host-template` marker.

The wrapper folds the ``IS_STACK_HOST`` gate into the module so callers
do not silently fail on hosts whose destination tree (compose dir,
nginx tree, keycloak admin volumes, ...) is owned exclusively by the
stack host. Keeping the bare ``template:`` module reachable re-opens
that class of bug.

Detection
=========
Line-based scan of every ``.yml`` file in the project. A finding is
recorded for every line that opens a ``template:`` (or
``ansible.builtin.template:``) task and does not carry the
``stack-host-template`` nocheck marker anywhere inside the task body.

Escape hatch
============
Add ``# nocheck: stack-host-template`` on the ``template:`` line, on
the ``src:`` line, or anywhere else inside the task body when the bare
``template:`` is genuinely required (per-host system config, app
compose dir that is structurally only ever materialised on STACK_HOST
via a parent IS_STACK_HOST gate, a fixture, ...). Use sparingly; each
suppression is a missed SPOT.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

TEMPLATE_MODULE_PATTERN = re.compile(
    r"^(?P<indent>\s*)-?\s*(ansible\.builtin\.template|template)\s*:\s*(?:#.*)?$"
)
NOCHECK_MARKER = "nocheck: stack-host-template"


def _find_task_block_end(lines: list[str], start_idx: int, base_indent: int) -> int:
    end = start_idx + 1
    while end < len(lines):
        line = lines[end]
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            indent = len(line) - len(stripped)
            if indent <= base_indent:
                break
        end += 1
    return end


class TestStackHostTemplateMigration(unittest.TestCase):
    def test_no_bare_template_without_stack_host_gate_or_nocheck(self):
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(extensions=(".yml",)):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if rel.startswith("tests/lint/"):
                continue

            lines = content.splitlines()
            for idx, line in enumerate(lines):
                match = TEMPLATE_MODULE_PATTERN.match(line)
                if not match:
                    continue
                base_indent = len(match.group("indent"))
                block_end = _find_task_block_end(lines, idx, base_indent)
                block_lines = lines[idx:block_end]

                if any(NOCHECK_MARKER in inner for inner in block_lines):
                    continue

                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(
                    findings, key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "Found bare `template:` tasks without the stack-host-template "
                "migration.\n\n"
                "Replace them with `stack_host_template:` so the IS_STACK_HOST "
                "gate is enforced centrally and workers no longer abort with "
                "'Destination directory does not exist'.\n\n"
                f"If a call site genuinely needs `template:` (per-host system "
                f"config, structurally parent-gated, fixture), suppress with "
                f"`# {NOCHECK_MARKER} (<reason>)`.\n\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
