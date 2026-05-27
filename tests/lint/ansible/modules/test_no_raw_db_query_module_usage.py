"""Forbid `community.postgresql.postgresql_query` / `community.mysql.mysql_query`
in role tasks; redirect callers to the project's `database_query` module
(``library/database_query.py``).

Rationale
=========
The community modules connect via TCP from the Ansible controller. With
non-shared databases (``services.<db>.shared=false`` variants), the
per-role ``<entity>-database`` container has no host port binding — the
controller can't reach it. `database_query` runs the query via
``container exec`` *inside* the DB container's network, so the same task
works in shared and non-shared mode without per-variant branching.

Per-line opt-out
================
Where the migration is intentionally deferred (or genuinely doesn't
apply — e.g. ``svc-db-postgres`` running psql against the DB it itself
manages), add ``# nocheck: database-query`` on the same line as the
module invocation, OR on the immediately preceding non-empty line. Use
``utils.annotations.suppress.is_suppressed_at`` semantics (``same-or-above``).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

# Match the module invocation as a YAML task key:
#   community.postgresql.postgresql_query:
#   postgresql_query:
#   community.mysql.mysql_query:
#   mysql_query:
# Captures optional trailing comment so the same line can carry a nocheck.
_RAW_DB_QUERY_MODULE_PATTERN = re.compile(
    r"^\s*("
    r"community\.postgresql\.postgresql_query"
    r"|postgresql_query"
    r"|community\.mysql\.mysql_query"
    r"|mysql_query"
    r")\s*:\s*(?:#.*)?$"
)

_RULE = "database-query"

# Files OUTSIDE role tasks where these modules might legitimately
# appear (e.g. this lint test's regex, the module docstring, contrib
# docs). Skipping these saves having to scatter nocheck markers in
# meta files / docs / fixtures.
_SCAN_PATH_PREFIX = "roles/"
_SCAN_PATH_INFIX = "/tasks/"


def _is_scan_target(rel_path: str) -> bool:
    return rel_path.startswith(_SCAN_PATH_PREFIX) and _SCAN_PATH_INFIX in rel_path


class TestNoRawDbQueryModuleUsage(unittest.TestCase):
    def test_role_tasks_use_database_query_or_carry_nocheck(self) -> None:
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(extensions=(".yml",)):
            yml_file = Path(path_str)
            rel = yml_file.relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue

            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _RAW_DB_QUERY_MODULE_PATTERN.match(line):
                    continue
                line_no = idx + 1
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
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
                "Found raw `community.postgresql.postgresql_query` / "
                "`community.mysql.mysql_query` module calls in role tasks.\n\n"
                "Migrate them to the project-local `database_query` module "
                "(`library/database_query.py`) so the same task works in "
                "shared and non-shared DB modes via `container exec`:\n\n"
                "    - name: <something>\n"
                "      database_query:\n"
                "        config: \"{{ lookup('database', application_id) }}\"\n"
                '        query_file: "{{ role_path }}/files/sql/<name>.sql"\n\n'
                "Or — only where the migration genuinely doesn't apply (e.g. "
                "`svc-db-postgres` running psql against the DB it itself manages) "
                "— add `# nocheck: database-query` on the same line or the line "
                "immediately above.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
