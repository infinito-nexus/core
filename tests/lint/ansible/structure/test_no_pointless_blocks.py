"""A bare ``block:`` wrapper is forbidden.

A ``block`` earns its indentation level only when it changes behaviour:
``rescue``/``always`` error handling, a shared ``when`` guard, or another
scoping key (``vars``, ``become``, ``delegate_to``, ``run_once``,
``environment``, ``no_log``, ``tags``, ...). A block whose only keys are
``name`` and ``block`` merely nests its tasks one level deeper - usually a
leftover from a removed ``rescue`` section. Remove the wrapper and inline
its tasks instead.
"""

from __future__ import annotations

import os
import unittest

from ruamel.yaml import (
    YAML,
)  # nocheck: direct-yaml — this lint needs task line numbers the yaml cache does not expose

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_ALLOWED_EXTRA_KEYS = frozenset({"name", "block"})
_yaml = YAML()


def _is_ansible_task_file(rel_path: str) -> bool:
    if not rel_path.startswith(("roles/", "tasks/")):
        return False
    if not rel_path.endswith((".yml", ".yaml")):
        return False
    return "/tasks/" in rel_path or "/handlers/" in rel_path


def _iter_block_tasks(node):
    """Yield every dict that carries a ``block`` key, anywhere in the tree."""
    if isinstance(node, list):
        for item in node:
            yield from _iter_block_tasks(item)
    elif isinstance(node, dict):
        if "block" in node:
            yield node
        for value in node.values():
            yield from _iter_block_tasks(value)


class TestNoPointlessBlocks(unittest.TestCase):
    def test_blocks_justify_their_wrapper(self):
        offenders: list[str] = []

        for abs_path, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml")
        ):
            rel_path = os.path.relpath(abs_path, PROJECT_ROOT)
            if not _is_ansible_task_file(rel_path):
                continue
            if "block:" not in content:
                continue
            try:
                doc = _yaml.load(content)  # nocheck: direct-yaml — line-aware parse
            except Exception:
                continue

            for task in _iter_block_tasks(doc):
                if set(task.keys()) - _ALLOWED_EXTRA_KEYS:
                    continue
                line = task.lc.line + 1
                offenders.append(
                    f"{rel_path}:{line}: bare block wrapper (only name+block; "
                    "no rescue/always/when or scoping key)"
                )

        if offenders:
            self.fail(
                f"{len(offenders)} pointless block wrapper(s). A block without "
                "rescue/always/when (or another scoping key like vars/become/"
                "delegate_to) only adds nesting - remove the wrapper and inline "
                "its tasks:\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
