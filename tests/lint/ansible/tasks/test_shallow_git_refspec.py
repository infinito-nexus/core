"""Lint: a shallow ``git`` checkout of a pinned ref survives its next update.

``git clone --depth N --branch <tag>`` leaves a detached HEAD and records no
``refs/remotes/<remote>/HEAD``. On the next run the module's ``fetch()`` calls
``get_head_branch()``, which reads that missing file, gets ``None`` and, since
ansible-core 2.21.6 (CVE-2026-84503 hardening), crashes on
``branch.startswith('-')`` with ``'NoneType' object has no attribute
'startswith'``.

A ``refspec`` keeps the clone off ``--branch``: git then clones the remote
HEAD branch, records ``origin/HEAD``, fetches the refspec and checks the ref
out, so every later update finds a head branch. ``single_branch: true`` puts
``--branch`` back and must not be combined with it.

Every ``git`` task that sets ``depth`` and a ``version`` other than ``HEAD``
MUST therefore set ``refspec`` and MUST NOT set ``single_branch: true``.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``nocheck: shallow-git-refspec`` on the module line or the one above it,
  when the version is always a branch, whose checkout keeps HEAD attached.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.invocations import iter_tasks

from . import PROJECT_ROOT
from .test_path_single_owner import module_line

_RULE = "shallow-git-refspec"

GIT_MODULES = ("git", "ansible.builtin.git", "ansible.legacy.git")

_TRUE_WORDS = frozenset({"true", "yes", "on", "1"})


def _is_true(value: Any) -> bool:
    return value is True or str(value).strip().lower() in _TRUE_WORDS


def offenders(tasks: Any) -> list[tuple[str, str, str]]:
    """Return ``(task name, module, missing fix)`` of every shallow checkout
    whose next update crashes.

    Args:
        tasks: a parsed task file.
    """
    found: list[tuple[str, str, str]] = []
    for task in iter_tasks(tasks):
        module = next((m for m in GIT_MODULES if isinstance(task.get(m), dict)), None)
        if module is None:
            continue
        args = task[module]
        if not args.get("depth"):
            continue
        if str(args.get("version", "HEAD")).strip() == "HEAD":
            continue
        if _is_true(args.get("single_branch", False)):
            found.append((str(task.get("name", "")), module, "drop single_branch"))
        elif not args.get("refspec"):
            found.append((str(task.get("name", "")), module, "add refspec"))
    return found


class TestShallowGitRefspec(unittest.TestCase):
    def test_every_shallow_pinned_checkout_sets_a_refspec(self) -> None:
        findings: list[str] = []
        for path in iter_project_files(
            extensions=(".yml", ".yaml"), exclude_tests=True
        ):
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            if "/tasks/" not in "/" + rel:
                continue
            found = offenders(load_yaml_any(path))
            if not found:
                continue
            lines = read_text(path).splitlines()
            for name, module, fix in found:
                line = module_line(lines, name, module)
                if is_suppressed_at(lines, line, _RULE, mode="same-or-above"):
                    continue
                findings.append(f"- {rel}:{line}: {name or '<unnamed>'} ({fix})")

        if findings:
            self.fail(
                "These shallow git checkouts of a pinned ref crash the next deploy "
                "with \"'NoneType' object has no attribute 'startswith'\" "
                "(ansible-core >= 2.21.6):\n"
                + "\n".join(findings)
                + "\n\nFix: add `refspec` (a tag `v1` takes "
                "`+refs/tags/v1:refs/tags/v1`) and drop `single_branch: true`, "
                f"or mark it `nocheck: {_RULE}` when the version is always a "
                "branch."
            )

    def test_tag_clone_without_refspec_is_found(self) -> None:
        tasks = [
            {
                "name": "pretix",
                "git": {"repo": "r", "dest": "d", "version": "v1", "depth": 1},
            }
        ]
        self.assertEqual(offenders(tasks), [("pretix", "git", "add refspec")])

    def test_single_branch_beside_refspec_is_found(self) -> None:
        tasks = [
            {
                "ansible.builtin.git": {
                    "version": "{{ REF }}",
                    "refspec": "+refs/tags/{{ REF }}:refs/tags/{{ REF }}",
                    "single_branch": True,
                    "depth": 1,
                }
            }
        ]
        self.assertEqual(
            offenders(tasks), [("", "ansible.builtin.git", "drop single_branch")]
        )

    def test_safe_shapes_pass(self) -> None:
        tasks = [
            {
                "git": {
                    "version": "v1",
                    "refspec": "+refs/tags/v1:refs/tags/v1",
                    "depth": 1,
                }
            },
            {"git": {"repo": "r", "depth": 1}},
            {"git": {"version": "HEAD", "depth": 1}},
            {"git": {"version": "v1", "single_branch": True}},
            {"block": [{"git": {"version": "v1", "refspec": "v1", "depth": 1}}]},
        ]
        self.assertEqual(offenders(tasks), [])

    def test_task_nested_in_a_block_is_found(self) -> None:
        tasks = [{"block": [{"git": {"version": "v1", "depth": 1}}]}]
        self.assertEqual(len(offenders(tasks)), 1)


if __name__ == "__main__":
    unittest.main()
