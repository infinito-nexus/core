"""Ansible ``rescue:`` blocks are forbidden.

Failure diagnostics are captured centrally: the CI workflows call
``utils/diagnostics/container.py`` on failure, which recurses through
every DiD level and snapshots containers, services, journal and host
resources from the outermost runner down to the innermost runtime. A
role-local rescue that merely captures diagnostics duplicates that and
swallows the real failure location.

Exception
---------

A rescue block MAY exist only when it genuinely must react to the failure
in-play (real recovery logic, or role-specific evidence that vanishes with
the failed task). Its FIRST task must carry a same-line
``# nocheck: rescue-<reason>`` comment (e.g. ``rescue-recovery``,
``rescue-extra-diagnostics``) justifying it. Such a block must end in a
task that re-raises the failure (the workflow-level capture still runs).
"""

from __future__ import annotations

import os
import re
import unittest

from ruamel.yaml import (
    YAML,
)  # nocheck: direct-yaml — this lint needs task line numbers the yaml cache does not expose

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_NOCHECK_RESCUE_RE = re.compile(r"#\s*nocheck:\s*rescue[\w-]*\b")
_yaml = YAML()


def _is_ansible_task_file(rel_path: str) -> bool:
    if not rel_path.startswith(("roles/", "tasks/")):
        return False
    if not rel_path.endswith((".yml", ".yaml")):
        return False
    return "/tasks/" in rel_path or "/handlers/" in rel_path


def _iter_rescue_seqs(node):
    """Yield every ``rescue`` task list found anywhere in the structure."""
    if isinstance(node, list):
        for item in node:
            yield from _iter_rescue_seqs(item)
    elif isinstance(node, dict):
        for key, value in node.items():
            if key == "rescue" and isinstance(value, list):
                yield value
            yield from _iter_rescue_seqs(value)


class TestNoRescueBlocks(unittest.TestCase):
    def test_rescue_blocks_are_forbidden_without_nocheck(self):
        offenders: list[str] = []

        for abs_path, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml")
        ):
            rel_path = os.path.relpath(abs_path, PROJECT_ROOT)
            if not _is_ansible_task_file(rel_path):
                continue
            if "rescue:" not in content:
                continue
            try:
                doc = _yaml.load(content)  # nocheck: direct-yaml — line-aware parse
            except Exception:
                continue
            lines = content.splitlines()

            for rescue in _iter_rescue_seqs(doc):
                tasks = [t for t in rescue if isinstance(t, dict)]
                if not tasks:
                    offenders.append(f"{rel_path}: empty rescue block")
                    continue
                first_line = lines[tasks[0].lc.line]
                if _NOCHECK_RESCUE_RE.search(first_line):
                    continue
                offenders.append(
                    f"{rel_path}:{tasks[0].lc.line + 1}: rescue block without a "
                    "`# nocheck: rescue-<reason>` justification on its first task"
                )

        if offenders:
            self.fail(
                f"{len(offenders)} forbidden rescue block(s). Failure diagnostics "
                "are captured by the workflow-level recursive rescue.py; delete "
                "the rescue block, or - only for genuine in-play recovery or "
                "vanishing role-specific evidence - justify it with a "
                "`# nocheck: rescue-<reason>` comment on its first task and end "
                "it with a task that re-raises the failure:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
