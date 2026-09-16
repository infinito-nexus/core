"""Lint: a ``loop_var`` may not take the name of a declared variable.

Ansible warns and carries on:

    [WARNING]: The variable 'application_id' is already in use.
    You should set the `loop_var` value in the `loop_control` option for the
    task to something else to avoid variable collisions and unexpected
    behavior.

Carrying on is the problem. Inside the loop the original value is gone, so
every lookup, template and nested include that reads the name sees the loop
item instead. The task still succeeds, which is why this shows up as a warning
in a log nobody greps rather than as a failure.

``application_id`` is the sharp case here: almost every role declares it and
``include_role`` carries it into whatever the loop body reaches, so a loop over
applications that names its item ``application_id`` silently repoints every
config lookup in the nested role.

Declared means: a key in ``group_vars/**`` or in any role's ``vars/main.yml``
or ``defaults/main.yml``. Cross-role includes are routine in this repository,
so a name another role declares is a name that can be in scope here.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``nocheck: loop-var-shadow`` on the ``loop_var`` line or the one above it,
  when the shadowing is deliberate and the loop body provably reads no other
  meaning of the name.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "loop-var-shadow"
_LOOP_VAR = re.compile(r"^\s*loop_var:\s*[\"']?(?P<name>[A-Za-z_][A-Za-z0-9_]*)")


def _declared_names() -> set[str]:
    """Every variable name the project declares in a file Ansible loads."""
    names: set[str] = set()
    for path in iter_project_files(extensions=(".yml", ".yaml"), exclude_tests=True):
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        is_group_var = rel.startswith("group_vars/")
        is_role_var = re.fullmatch(r"roles/[^/]+/(vars|defaults)/main\.ya?ml", rel)
        if not (is_group_var or is_role_var):
            continue
        loaded = load_yaml_any(path)
        if isinstance(loaded, dict):
            names.update(key for key in loaded if isinstance(key, str))
    return names


def _task_files() -> list[str]:
    return sorted(
        path
        for path in iter_project_files(extensions=(".yml", ".yaml"), exclude_tests=True)
        if "/tasks/" in Path(path).relative_to(PROJECT_ROOT).as_posix()
    )


class TestLoopVarShadowing(unittest.TestCase):
    def test_no_loop_var_shadows_a_declared_variable(self) -> None:
        declared = _declared_names()
        self.assertTrue(
            declared, "no variable declarations were found to compare against"
        )

        findings: list[str] = []
        for path in _task_files():
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            lines = read_text(path).splitlines()
            for index, line in enumerate(lines):
                match = _LOOP_VAR.match(line)
                if match is None or match.group("name") not in declared:
                    continue
                if is_suppressed_at(lines, index + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append(f"- {rel}:{index + 1}: loop_var: {match.group('name')}")

        if findings:
            self.fail(
                "These loops name their item after a variable the project "
                "declares, so inside the loop that variable carries the item "
                "instead of its own value and every nested lookup reads the "
                "wrong thing:\n"
                + "\n".join(findings)
                + "\n\nFix: give the loop item a name of its own, for example "
                f"`loop_var: <role>_item`, or mark it `nocheck: {_RULE}` when the "
                "loop body provably reads no other meaning of the name."
            )


if __name__ == "__main__":
    unittest.main()
