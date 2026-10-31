"""Require a failure path wherever `changed_when` tests a SQL row count.

A `changed_when: "'UPDATE 1' in result.stdout"` says the author already
knows the statement can affect a different number of rows. A client-side
`UPDATE` that matches nothing is not an error to `psql` or `mysql`: the tag
reads `UPDATE 0`, the exit status stays 0, and `ON_ERROR_STOP` is silent
because no SQL error occurred. Ansible then reports the task `ok`.

For a credential realign that outcome is a false green. Two shipped tasks
reached it: listmonk patched a hardcoded `administrator` on a deployment
whose account is named `platformadmin`, and the matrix flavors point at an
account the play may never have created. Both reported success while
realigning nothing.

So a row-count test needs a `failed_when` that says what the other counts
mean. The usual form is the complement of `changed_when`, since these
statements rewrite unconditionally and `UPDATE 1` is therefore the only
successful outcome.

Per-line opt-out
================
`# nocheck: sql-rowcount-needs-failure -- <reason>` on the `changed_when`
line or the one above it, for a statement whose zero-row result is a
legitimate no-op; name the row it may miss.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "sql-rowcount-needs-failure"
_EXTENSIONS = (".yml", ".yaml")
_ROW_COUNT = re.compile(r"\b(UPDATE|DELETE|INSERT\s+0|SELECT)\s+[1-9]")


def _expression(value) -> str:
    """Flatten a condition into one searchable string.

    Args:
        value: the raw `changed_when`/`failed_when` node, which Ansible
            accepts as a scalar or as a list it ANDs together.

    Returns:
        The condition as text, empty when the key was absent.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return " and ".join(str(item) for item in value)
    return str(value)


def _tasks(node):
    if isinstance(node, dict):
        if "changed_when" in node:
            yield node
        for value in node.values():
            yield from _tasks(value)
    elif isinstance(node, list):
        for item in node:
            yield from _tasks(item)


class TestRowCountNeedsFailure(unittest.TestCase):
    def test_a_row_count_test_states_what_other_counts_mean(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=_EXTENSIONS
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith("roles/") or "/tasks/" not in rel:
                continue
            try:
                doc = load_yaml_any(path_str)
            except Exception:  # pragma: no cover - malformed YAML is another rule's
                continue
            lines = content.splitlines()
            for task in _tasks(doc):
                changed = _expression(task.get("changed_when"))
                if not _ROW_COUNT.search(changed):
                    continue
                failed = _expression(task.get("failed_when"))
                if failed and failed.strip().lower() != "false":
                    continue
                line_no = next(
                    (
                        number
                        for number, line in enumerate(lines, 1)
                        if "changed_when" in line and _ROW_COUNT.search(line)
                    ),
                    1,
                )
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, line_no, str(task.get("name", ""))[:60]))

        if findings:
            formatted = "\n".join(
                f"- {p}:{ln}: {name}"
                for p, ln, name in sorted(set(findings), key=lambda x: (x[0], x[1]))
            )
            self.fail(
                f"Found {len(set(findings))} task(s) whose `changed_when` tests a "
                "SQL row count but which declare no `failed_when`. A statement "
                "that matches no row returns `UPDATE 0` with exit status 0, so "
                "the task reports `ok` for both 'the row was rewritten' and 'the "
                "row this targets does not exist'.\n\n"
                "Fix: add the complement as `failed_when`, e.g. `failed_when: "
                "<result>.rc != 0 or 'UPDATE 1' not in <result>.stdout`, so a "
                "statement that finds nothing fails the play.\n\n"
                f"Offending tasks:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
