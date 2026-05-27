"""Lint guard: tests MUST route project-tree walks through
``utils.cache.files`` instead of calling ``Path.rglob(...)`` /
``os.walk(...)`` / ``glob.glob(...)`` directly.

Background
==========
Pytest runs every test in one process. A raw walk over the repo tree
re-iterates the same paths and re-stats the same inodes for every test
that needs them, which scales linearly with the number of lint /
integration tests doing project scans. Routing every walk through
:func:`utils.cache.files.iter_project_files` (or
:func:`iter_project_files_with_content`, :func:`read_text`) shares one
walk + one read per file across the whole pytest session.

See ``docs/agents/action/testing.md`` for the full rule.

Detection
=========
AST-walks every ``.py`` file under ``tests/`` and flags call
expressions matching the forbidden shapes:

* ``<x>.rglob(...)``  — Path/PurePath recursive glob
* ``os.walk(...)``    — top-down/bottom-up directory walker
* ``glob.glob(...)``  — pattern-based glob (recursive or not)

Aliased ``glob`` imports are tracked: ``import glob as G`` ⇒ ``G.glob(...)``
is flagged; ``from glob import glob`` ⇒ bare ``glob(...)`` is flagged.

Plain attribute access without a call is NOT flagged. String literals,
docstrings and comments naming these functions in prose are also not
flagged because the AST sees only real call nodes.

Per-line opt-out
================
Add ``# nocheck: project-walk`` (or ``# nocheck: project-walk``;
case-insensitive) on the call's own line OR, for multi-line calls, on
any line spanned by the call expression. Use this for legitimate
exceptions that genuinely need a raw walk and that have been audited —
e.g. tests that scan a tempdir created at runtime, or tests that probe
``.git`` history. Do NOT use it to silence the lint for "I want the
convenience of rglob" — refactor the test to use
``iter_project_files`` instead.

The marker grammar lives in
``docs/contributing/actions/testing/suppression.md``; this lint
consumes it via :func:`utils.annotations.suppress.suppressed_line_numbers`.
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.annotations.suppress import suppressed_line_numbers
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "project-walk"
_TESTS_PREFIX = "tests/"


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    pattern: str
    snippet: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return f"{rel}:{self.line}: {self.pattern}: {self.snippet}"


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        src = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return findings

    lines = src.splitlines()
    noqa = suppressed_line_numbers(lines, _RULE)

    # Track names bound to the `glob` module (`import glob`,
    # `import glob as G`) and to the bare `glob.glob` import
    # (`from glob import glob`, `from glob import glob as g`).
    glob_module_aliases: set[str] = set()
    direct_glob_aliases: set[str] = set()
    # Same for `os` so we recognise `import os as O; O.walk(...)`.
    os_module_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "glob":
                    glob_module_aliases.add(alias.asname or "glob")
                elif alias.name == "os":
                    os_module_aliases.add(alias.asname or "os")
        elif isinstance(node, ast.ImportFrom) and node.module == "glob":
            for alias in node.names:
                if alias.name == "glob":
                    direct_glob_aliases.add(alias.asname or "glob")

    def _is_noqa(node: ast.Call) -> bool:
        start = node.lineno
        end = getattr(node, "end_lineno", node.lineno)
        return any(line in noqa for line in range(start, end + 1))

    def _snippet(node: ast.Call) -> str:
        idx = node.lineno - 1
        if 0 <= idx < len(lines):
            return lines[idx].strip()[:160]
        return ""

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        label: str | None = None
        if isinstance(func, ast.Attribute):
            # `<x>.rglob(...)` — receiver may be any expression
            if func.attr == "rglob":
                label = "rglob"
            # `os.walk(...)` (incl. aliased os module)
            elif (
                func.attr == "walk"
                and isinstance(func.value, ast.Name)
                and func.value.id in os_module_aliases
            ):
                label = "os.walk"
            # `glob.glob(...)` (incl. aliased glob module)
            elif (
                func.attr == "glob"
                and isinstance(func.value, ast.Name)
                and func.value.id in glob_module_aliases
            ):
                label = "glob.glob"
        elif isinstance(func, ast.Name) and func.id in direct_glob_aliases:
            # `from glob import glob` ⇒ bare `glob(...)`
            label = "glob.glob"

        if label is None:
            continue
        if _is_noqa(node):
            continue
        findings.append(
            Finding(
                file=path,
                line=node.lineno,
                pattern=label,
                snippet=_snippet(node),
            )
        )

    return findings


class TestNoRawProjectWalk(unittest.TestCase):
    def test_tests_use_iter_project_files_instead_of_raw_walks(self) -> None:
        """Forbidden call shapes in test code without an explicit
        ``# nocheck: project-walk`` marker. Use
        :func:`utils.cache.files.iter_project_files` so the project-tree
        walk is shared across the pytest session."""
        repo_root = PROJECT_ROOT

        findings: list[Finding] = []
        for path_str in iter_project_files(extensions=(".py",)):
            rel = Path(path_str).relative_to(repo_root).as_posix()
            if not rel.startswith(_TESTS_PREFIX):
                continue
            findings.extend(_scan_file(Path(path_str)))

        if findings:
            formatted = "\n".join(f.format(repo_root) for f in findings)
            self.fail(
                f"{len(findings)} raw project-tree walk call(s) in test code:\n"
                f"{formatted}\n\n"
                "FIX: replace with one of the cached helpers from "
                "`utils.cache.files`:\n"
                '  • iter_project_files(extensions=(".yml",))     → yields paths\n'
                "  • iter_project_files_with_content(...)        → yields (path, text)\n"
                "  • read_text(path)                              → cached UTF-8 read\n"
                "These share one filesystem walk + one read per file across the\n"
                "whole pytest session. See docs/agents/action/testing.md.\n\n"
                "Only opt out per call with `# nocheck: project-walk` when the walk\n"
                "is genuinely outside the project tree (tempdirs, `.git` history,\n"
                "etc.) and a short inline comment explains why."
            )


if __name__ == "__main__":
    unittest.main()
