from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
SCANNED = ("templates", "files", "tasks", "vars")
SUFFIXES = {".j2", ".sql", ".yml", ".yaml", ".py", ".sh"}
INSERT = re.compile(
    r"INSERT\s+INTO\s+(?:public\.)?runner\s*\(([^)]*)\)\s*(?:SELECT|VALUES)\s*(.*?)(?:\bFROM\b|\bWHERE\b|\bRETURNING\b|;)",
    re.IGNORECASE | re.DOTALL,
)
UPDATE = re.compile(
    r"UPDATE\s+(?:public\.)?runner\b(?:\s+AS\s+\w+)?\s+SET\s+(.*?)(?:\bFROM\b|\bWHERE\b|\bRETURNING\b|;)",
    re.IGNORECASE | re.DOTALL,
)
NULL_PROJECT = re.compile(r"\bproject_id\s*=\s*NULL\b", re.IGNORECASE)
NULL_VALUE = re.compile(r"^NULL\b", re.IGNORECASE)
PLANTED_INSERT = """INSERT INTO public.runner (project_id, token, webhook, max_parallel_tasks, name, active, is_default)
SELECT NULL, :'runner_token', '', 0, :'runner_name', TRUE, TRUE
WHERE NOT EXISTS (
  SELECT 1
  FROM public.runner
  WHERE name = :'runner_name'
)
RETURNING 'CHANGED runner ' || name || ' created';
"""


def top_level(values):
    """Args:
    values: the value list of an ``INSERT``, without its outer parentheses.

    Returns:
        The values split at every comma outside parentheses and quotes.
    """
    parts, depth, quoted, current = [], 0, False, ""
    for char in values:
        if char == "'":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        if char == "," and depth == 0 and not quoted:
            parts.append(current.strip())
            current = ""
            continue
        current += char
    parts.append(current.strip())
    return parts


def statement_findings(where, text):
    """Args:
    where: how a finding names the file.
    text: the file's text.

    Returns:
        Every statement of ``text`` that writes a runner row without a project.
    """
    findings = []
    for match in INSERT.finditer(text):
        columns = [c.strip().lower() for c in match.group(1).split(",")]
        values = top_level(match.group(2).strip().removeprefix("(").removesuffix(")"))
        if "project_id" not in columns:
            findings.append(f"{where}: a runner INSERT names no project_id")
        elif NULL_VALUE.match(values[columns.index("project_id")]):
            findings.append(f"{where}: a runner INSERT writes project_id NULL")
    findings.extend(
        f"{where}: a runner UPDATE sets project_id NULL"
        for match in UPDATE.finditer(text)
        if NULL_PROJECT.search(match.group(1))
    )
    return findings


def role_findings(role):
    """Args:
    role: the role directory.

    Returns:
        Every runner row without a project the role's SQL, tasks, files or
        variables write.
    """
    findings = []
    for folder in SCANNED:
        scanned = f"{role / folder}{os.sep}"
        for path in sorted(iter_project_files(extensions=tuple(SUFFIXES))):
            if path.startswith(scanned):
                findings += statement_findings(
                    Path(path).relative_to(role).as_posix(), read_text(path)
                )
    return findings


class TestSemaphoreRunnerRows(unittest.TestCase):
    def test_every_runner_row_names_a_project(self):
        self.assertEqual(role_findings(ROLE), [])
        self.assertGreaterEqual(
            len(
                INSERT.findall(
                    read_text(
                        str(ROLE / "templates" / "sql" / "project" / "runners.sql.j2")
                    )
                )
            ),
            1,
        )

    def test_the_check_catches_a_null_project_insert(self):
        self.assertEqual(
            statement_findings("prepare.sql.j2", PLANTED_INSERT),
            ["prepare.sql.j2: a runner INSERT writes project_id NULL"],
        )

    def test_negative_control_an_update_to_a_null_project_is_reported(self):
        self.assertEqual(
            statement_findings(
                "x.sql",
                "UPDATE public.runner\nSET project_id = NULL\nWHERE name = 'x';",
            ),
            ["x.sql: a runner UPDATE sets project_id NULL"],
        )

    def test_negative_control_an_insert_without_project_id_is_reported(self):
        self.assertEqual(
            statement_findings(
                "x.sql", "INSERT INTO public.runner (token, name) VALUES ('t', 'n');"
            ),
            ["x.sql: a runner INSERT names no project_id"],
        )

    def test_a_tag_row_is_no_runner_row(self):
        self.assertEqual(
            statement_findings(
                "x.sql",
                "INSERT INTO public.runner__tag (runner_id, tag) SELECT NULL, 'x';",
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
