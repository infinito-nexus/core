"""Lint: a value handed to a stack include must not read ``application_id``.

``vars:`` on an ``include_role`` reaches everything the include pulls in, and
the expression is evaluated where it is used rather than where it is written.
``sys-stk-full`` pulls in the proxy and the database, and those roles set
``application_id`` to their own id, so an expression that reads it resolves
against the wrong application by the time anyone asks for it.

It fails as a missing key in a role that never declared the value: a repository
url written by one app was looked up on ``svc-prx-openresty``, which has no such
service, and the git task died on an unresolvable argument.

Naming the application literally makes the expression answer the same in every
scope it travels through.

Only the ``compose_*`` keys are judged, because only those does the included
chain evaluate. A value nobody downstream reads is merely in scope and harmless;
matching every handed-over key instead reported thirteen values, six of them
nothing.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: stack-var-foreign-scope`` on, or directly above, the definition.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_RULE = "stack-var-foreign-scope"
_STACK_INCLUDE = "sys-stk-full"

_PASSED_RE = re.compile(
    r"^\s+(compose_[a-z_]+):\s*\"\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}\""
)
_SCOPED_RE = re.compile(r"(?<![\w.])(application_id|entity_name)\b")


def passed_into_stack(role) -> set[str]:
    """Return the variable names a role hands to the stack include.

    Args:
        role: the role directory.
    """
    passed: set[str] = set()
    for path in sorted(role.glob("tasks/**/*.yml")):
        lines = read_text(str(path)).splitlines()
        for index, line in enumerate(lines):
            if _STACK_INCLUDE not in line:
                continue
            for following in lines[index : index + 12]:
                match = _PASSED_RE.match(following)
                if match:
                    passed.add(match.group(2))
    return passed


def definitions_reading_scope(role, names: set[str]) -> list[str]:
    """Return one finding per handed-over definition that reads the scope.

    Args:
        role: the role directory.
        names: the variable names the role hands to the stack include.
    """
    variables = role / ROLE_FILE_VARS_MAIN
    if not names or not variables.is_file():
        return []
    findings = []
    lines = read_text(str(variables)).splitlines()
    for index, line in enumerate(lines, start=1):
        name = line.split(":", 1)[0].strip()
        if name not in names or not _SCOPED_RE.search(line):
            continue
        if is_suppressed_at(lines, index, _RULE):
            continue
        findings.append(
            f"{variables.relative_to(PROJECT_ROOT)}:{index}: {name} is handed to "
            f"{_STACK_INCLUDE} and resolves against whichever role reads it"
        )
    return findings


def stack_vars_reading_foreign_scope() -> list[str]:
    """Return one finding per value that would resolve in a foreign role."""
    findings = []
    for role in sorted((PROJECT_ROOT / "roles").iterdir()):
        if not role.is_dir():
            continue
        findings.extend(definitions_reading_scope(role, passed_into_stack(role)))
    return findings


class TestStackVarsResolveInTheirOwnRole(unittest.TestCase):
    def test_no_handed_over_value_reads_the_reader_s_scope(self) -> None:
        findings = stack_vars_reading_foreign_scope()
        self.assertEqual(
            [],
            findings,
            f"value(s) that resolve against the wrong role ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_shape_it_guards_is_actually_in_use(self) -> None:
        """Without one, a renamed include would let the rule pass over everything."""
        handing = [
            role
            for role in sorted((PROJECT_ROOT / "roles").iterdir())
            if role.is_dir() and passed_into_stack(role)
        ]
        self.assertGreater(len(handing), 3, "no role hands a value to the stack")


if __name__ == "__main__":
    unittest.main()
