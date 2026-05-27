"""Forbid raw inline ``query:`` on ``database_query:`` tasks; prefer
``query_file:`` so SQL stays reviewable on disk.

Rationale
=========
The ``database_query`` module supports both ``query`` (raw string) and
``query_file`` (path to a ``.sql`` file). For readability, diffability,
and reuse, role tasks should reference a ``.sql`` file via
``query_file:`` whenever the SQL is non-trivial. Inline ``query:`` is
kept as a valid escape hatch for the few cases where the SQL is the
result of a Jinja ``lookup('template', '...sql.j2')`` and cannot
naturally be pinned to a static path.

Per-line opt-out
================
Where inline ``query:`` is genuinely the right call (e.g. the SQL
content is computed at runtime via a template lookup), add
``# nocheck: database-query-raw`` on the same line as the ``query:``
key OR on the immediately preceding non-empty line. The check uses
``utils.annotations.suppress.is_suppressed_at`` semantics
(``same-or-above``).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

# Match a ``query:`` key whose IMMEDIATELY preceding non-blank line
# is `database_query:` (any indent depth). We scan top-down so we can
# carry that one-step look-back without a full YAML parse.
_QUERY_KEY_PATTERN = re.compile(r"^\s*query\s*:")
_DATABASE_QUERY_PATTERN = re.compile(r"^\s*database_query\s*:")

_RULE = "database-query-raw"
_SCAN_PATH_PREFIX = "roles/"
_SCAN_PATH_INFIX = "/tasks/"


def _is_scan_target(rel_path: str) -> bool:
    return rel_path.startswith(_SCAN_PATH_PREFIX) and _SCAN_PATH_INFIX in rel_path


def _previous_non_blank_index(lines: list[str], idx: int) -> int | None:
    """Return the index of the most recent non-blank line strictly
    before ``idx``, or ``None`` if none exists.
    """
    for prev in range(idx - 1, -1, -1):
        if lines[prev].strip():
            return prev
    return None


class TestNoRawDatabaseQueryString(unittest.TestCase):
    def test_database_query_tasks_use_query_file_or_carry_nocheck(self) -> None:
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(extensions=(".yml",)):
            yml_file = Path(path_str)
            rel = yml_file.relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue

            lines = content.splitlines()
            in_database_query_block = False
            database_query_indent: int | None = None

            for idx, line in enumerate(lines):
                stripped = line.lstrip()
                if not stripped:
                    continue
                line_indent = len(line) - len(stripped)

                # Enter / leave the inner mapping of a `database_query:`
                # task. The block is open until a sibling/dedented key
                # closes it.
                if _DATABASE_QUERY_PATTERN.match(line):
                    in_database_query_block = True
                    database_query_indent = line_indent
                    continue

                if in_database_query_block and database_query_indent is not None:
                    if line_indent <= database_query_indent:
                        in_database_query_block = False
                        database_query_indent = None
                    elif _QUERY_KEY_PATTERN.match(line):
                        line_no = idx + 1
                        if is_suppressed_at(
                            lines, line_no, _RULE, mode="same-or-above"
                        ):
                            continue
                        findings.append((rel, line_no, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(
                    findings, key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "Found inline `query:` on `database_query:` tasks. "
                "Prefer `query_file:` so SQL stays reviewable on disk:\n\n"
                "    - name: <something>\n"
                "      database_query:\n"
                "        config: \"{{ lookup('database', application_id) }}\"\n"
                '        query_file: "{{ role_path }}/files/sql/<name>.sql"\n'
                "        named_args:\n"
                '          some_value: "{{ some_variable }}"\n\n'
                "Or — only where the SQL is the result of a Jinja lookup "
                "(`{{ lookup('template', '...sql.j2') }}`) and cannot be pinned "
                "to a static path — add `# nocheck: database-query-raw` on the "
                "same line or the line immediately above.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
