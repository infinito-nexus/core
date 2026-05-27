"""Forbid more than 3 lines of inline SQL embedded in Ansible task YAML.

When a role needs to run a non-trivial SQL block (admin-user bootstrap,
RBAC seeding, idempotent UPSERTs, etc.) the SQL MUST live in a dedicated
`files/<name>.sql` file and be loaded via the file lookup plugin into a
`shell:` / `command:` task that pipes it through stdin to `psql -f -` or
`mysql --execute=... < /path` style invocations.

Why
---
* Embedding multi-line SQL inside YAML scalars couples shell quoting,
  Jinja interpolation and SQL escaping into the same scalar — the
  brittle interaction is what produced
  `psql: ERROR: syntax error at or near ":"` on the colon-prefixed
  variable form (`:'var'`) when piped through `psql -c "..."` instead of
  stdin.
* `.sql` files round-trip cleanly through editors / linters / language
  servers and stay reviewable in isolation from the orchestration glue.
* `lookup('file', '<name>.sql')` keeps the SQL content hashable for
  `changed_when` decisions and avoids the `script:` module's awkward
  positional-argument wrapping.

The lint flags any YAML scalar value (under any key) that contains more
than 3 lines whose stripped form starts with a SQL keyword. Anything
shorter is judged to fit safely as an inline statement.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable

SCAN_DIRS = ("roles", "tasks", "playbooks")
_SCAN_PREFIXES = tuple(f"{d}/" for d in SCAN_DIRS)
SCAN_SUFFIXES = (".yml", ".yaml")

_INLINE_SQL_THRESHOLD = 3

# Keyword leaders that strongly imply the line is real SQL (rather than
# bash, Jinja, log output, or comment text). Anchored at the start of the
# stripped line and case-insensitive.
_SQL_KEYWORD_LEADERS = (
    "ALTER ",
    "BEGIN;",
    "BEGIN ",
    "COMMIT;",
    "COMMIT ",
    "CREATE ",
    "DELETE ",
    "DO $$",
    "DROP ",
    "FROM ",
    "GRANT ",
    "INSERT ",
    "JOIN ",
    "MERGE ",
    "ON CONFLICT ",
    "REVOKE ",
    "ROLLBACK;",
    "ROLLBACK ",
    "SELECT ",
    "SET ",
    "TRUNCATE ",
    "UPDATE ",
    "UPSERT ",
    "VALUES ",
    "WHERE ",
    "WITH ",
)

# Files we must not scan to avoid recursive false positives.
_EXCLUDED_RELATIVE_PATHS = frozenset(
    {
        "tests/lint/ansible/sql/test_no_inline_multiline_sql.py",  # nocheck: self-path-reference
    }
)


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    sql_line_count: int
    sample: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return (
            f"{rel}:{self.line}: {self.sql_line_count} SQL-looking lines "
            f"in inline scalar — extract to files/<name>.sql and load "
            f"via lookup('file', ...)\n  first SQL line: {self.sample!r}"
        )


def _iter_target_files(repo_root: Path) -> Iterable[Path]:
    for abs_path in iter_project_files(extensions=SCAN_SUFFIXES):
        rel = Path(abs_path).relative_to(repo_root).as_posix()
        if rel in _EXCLUDED_RELATIVE_PATHS:
            continue
        if any(rel.startswith(p) for p in _SCAN_PREFIXES):
            yield Path(abs_path)


def _is_sql_line(line: str) -> bool:
    stripped = line.strip().upper()
    return any(stripped.startswith(kw) for kw in _SQL_KEYWORD_LEADERS)


def _count_sql_lines(value: str) -> tuple[int, str]:
    """Return ``(consecutive_sql_line_count, first_sql_line)`` for the
    longest run of SQL-looking lines inside *value*. Empty / whitespace
    lines do not break the run; a run is only broken by a non-empty line
    that does not look like SQL.
    """
    best_run = 0
    best_first = ""
    current_run = 0
    current_first = ""
    for raw in value.splitlines():
        if not raw.strip():
            continue
        if _is_sql_line(raw):
            if current_run == 0:
                current_first = raw.strip()
            current_run += 1
            if current_run > best_run:
                best_run = current_run
                best_first = current_first
        else:
            current_run = 0
            current_first = ""
    return best_run, best_first


def _walk_scalars(node, prefix: str = "") -> Iterable[tuple[str, str]]:
    """Yield ``(key_path, value)`` for every string scalar reachable from
    *node*. Lists are walked, dict values are walked.
    """
    if isinstance(node, str):
        yield prefix, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_scalars(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _walk_scalars(item, f"{prefix}[{i}]")


def _approximate_lineno(text: str, value: str) -> int:
    """Best-effort source line number for *value* inside *text*. Falls
    back to the first line of *text* when the scalar can't be located —
    the line number is informational, not load-bearing for the lint.
    """
    if not value:
        return 1
    first_sql_line = ""
    for raw in value.splitlines():
        if _is_sql_line(raw):
            first_sql_line = raw.strip()
            break
    if not first_sql_line:
        return 1
    needle = first_sql_line.split()[0]
    pat = re.compile(rf"\b{re.escape(needle)}\b", re.IGNORECASE)
    for i, src_line in enumerate(text.splitlines(), start=1):
        if pat.search(src_line):
            return i
    return 1


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    data = load_yaml_any(str(path), default_if_missing=None)
    if data is None:
        return findings
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings
    for _key_path, value in _walk_scalars(data):
        if "\n" not in value:
            continue
        run, sample = _count_sql_lines(value)
        if run > _INLINE_SQL_THRESHOLD:
            findings.append(
                Finding(
                    file=path,
                    line=_approximate_lineno(text, value),
                    sql_line_count=run,
                    sample=sample,
                )
            )
    return findings


class TestNoInlineMultilineSQL(unittest.TestCase):
    def test_no_more_than_three_sql_lines_inline_in_tasks(self) -> None:
        repo_root = PROJECT_ROOT
        findings: list[Finding] = []
        for path in _iter_target_files(repo_root):
            findings.extend(_scan_file(path))
        if not findings:
            return
        formatted = "\n".join(f.format(repo_root) for f in findings)
        self.fail(
            f"{len(findings)} task YAML scalar(s) contain more than "
            f"{_INLINE_SQL_THRESHOLD} lines of inline SQL.\n\n"
            "Move the SQL into a dedicated `files/<name>.sql` file and "
            "load it from the task via the file lookup plugin, e.g.:\n\n"
            '    - name: "Run idempotent UPSERT"\n'
            "      ansible.builtin.shell:\n"
            "        cmd: |\n"
            "          container exec -i {{ db_container }} \\\n"
            "            psql -U {{ db_user }} -d {{ db_name }} \\\n"
            "                 -v ON_ERROR_STOP=1 \\\n"
            "                 -v key={{ value | quote }}\n"
            "        stdin: \"{{ lookup('file', '<name>.sql') }}\"\n\n"
            f"Findings:\n{formatted}"
        )


if __name__ == "__main__":
    unittest.main()
