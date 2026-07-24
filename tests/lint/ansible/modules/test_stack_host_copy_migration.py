"""Drift guard: every ``copy:`` task that writes into an app's compose /
build-context directory (``directories.instance``) must adopt the project's
:mod:`plugins.action.stack_host_copy` wrapper or carry an explicit
``# nocheck: stack-host-copy`` marker.

``stack_host_copy`` is the ``copy:`` analogue of
:mod:`plugins.action.stack_host_template`: it folds the ``IS_STACK_HOST``
gate into the module so callers do not silently fail on hosts whose
destination tree is owned exclusively by the stack host. In swarm the
compose / build-context directory of an app (``/opt/compose/<app>``) is
materialised only on the stack host (the manager); a bare ``copy:`` whose
``dest`` resolves through ``lookup('container', <app>,
'directories.instance')`` therefore also runs on every worker and aborts
the play with ``Destination directory ... does not exist`` -- the
trusted-header SSO build-context staging (``Dockerfile`` + ``sso/*.py``)
hit exactly this across several web-app roles.

Detection
=========
Line-based scan of every ``.yml`` file in the project. A finding is
recorded for every ``copy:`` (or ``ansible.builtin.copy:``) task whose
module body references ``directories.instance`` and does not carry the
``stack-host-copy`` nocheck marker. Replace the module key with
``stack_host_copy:`` -- the args (``src``/``dest``/``mode``/``loop``) are
unchanged and the manual ``when: IS_STACK_HOST`` becomes redundant.

Escape hatch
============
Add ``# nocheck: stack-host-copy`` on the ``copy:`` line, on the ``src:``
line, or anywhere else inside the task body when the bare ``copy:`` is
genuinely required (a destination that is not the stack-host-only compose
dir, a fixture, ...). Use sparingly; each suppression is a missed SPOT.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

COPY_MODULE_PATTERN = re.compile(
    r"^(?P<indent>\s*)-?\s*(ansible\.builtin\.copy|copy)\s*:\s*(?:#.*)?$"
)
INSTANCE_MARKER = "directories.instance"
NOCHECK_MARKER = "nocheck: stack-host-copy"


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


class TestStackHostCopyMigration(unittest.TestCase):
    def test_no_bare_copy_into_compose_dir_without_wrapper_or_nocheck(self):
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(extensions=(".yml",)):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if rel.startswith("tests/lint/"):
                continue

            lines = content.splitlines()
            for idx, line in enumerate(lines):
                match = COPY_MODULE_PATTERN.match(line)
                if not match:
                    continue
                base_indent = len(match.group("indent"))
                block_end = _find_task_block_end(lines, idx, base_indent)
                block_lines = lines[idx:block_end]

                if not any(INSTANCE_MARKER in inner for inner in block_lines):
                    continue  # not a write into the compose / build-context dir
                if any(NOCHECK_MARKER in inner for inner in block_lines):
                    continue  # explicitly suppressed

                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(
                    findings, key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "Found bare `copy:` tasks that stage files into the app compose "
                "/ build-context directory (directories.instance) without the "
                "stack-host-copy migration.\n\n"
                "Replace the module key with `stack_host_copy:` so the "
                "IS_STACK_HOST gate is enforced centrally and workers no longer "
                "abort with 'Destination directory does not exist'. The args are "
                "unchanged; a manual `when: IS_STACK_HOST` then becomes "
                "redundant.\n\n"
                f"If a call site genuinely needs `copy:` (destination is not the "
                f"stack-host-only compose dir, fixture), suppress with "
                f"`# {NOCHECK_MARKER} (<reason>)`.\n\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
