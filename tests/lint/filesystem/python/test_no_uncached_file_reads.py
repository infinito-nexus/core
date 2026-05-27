"""Lint guard: tests and the modules they import MUST route file reads
through ``utils.cache.files.read_text`` instead of calling
``Path.read_text(...)`` or ``Path.read_bytes(...)`` directly.

Background
==========
Pytest runs every test in one process. The test suite reads the
same role/task YAML, Dockerfile, packaging spec, compose template,
nginx conf, etc. dozens of times across sibling tests.
``utils.cache.files.read_text`` is an LRU-cached UTF-8 read keyed on
absolute path — every duplicate scan after the first one returns from
memory. A raw ``path.read_text(...)`` call bypasses that cache and
re-reads the file from disk every time.

The cost is invisible at the call site but measurable at suite level:
each non-cached read is one ``open() + read() + decode + close()``
syscall round-trip per test that asks for it. On the lint pass alone
(20+ scanners, ~250 role trees) the wasted reads add up to seconds of
cold-cache latency that no individual test owner notices. Integration
tests show the same pattern (e.g. one role's compose template read
across multiple shape tests).

The same logic applies to library code (``utils/``, ``cli/``,
``plugins/``, ``library/``) when tests import those modules and call
their functions directly: their raw reads run inside the same process
and bypass the cache the tests just populated.

See ``docs/agents/action/testing.md`` for the full rule.

Scope
=====
Every ``.py`` file under ``tests/``, ``utils/``, ``cli/``, ``plugins/``,
and ``library/`` is scanned. ``utils/cache/`` is excluded because it
holds the cache implementation itself (would self-reference).
``roles/`` is excluded because its scripts are deployed to target
hosts without ``utils/`` on PYTHONPATH. Legitimate exceptions — reads
from a tempdir created at runtime, synthetic fixtures written inside
the test, files mutated in the same flow that re-reads them — opt
out per call with ``# nocheck: cache-read``.

Detection
=========
AST-walks every ``.py`` file in scope and flags call expressions
matching::

    <expr>.read_text(...)
    <expr>.read_bytes(...)

The receiver is not type-inferred — every method call with that
attribute name is flagged, on the assumption that the receiver is a
``Path`` (which is the overwhelming convention in this codebase). False
positives on differently-typed receivers should opt out per call.

Plain attribute access without a call is NOT flagged. String literals,
docstrings and comments naming these methods in prose are also not
flagged because the AST sees only real call nodes.

Per-line opt-out
================
Add ``# nocheck: cache-read`` (or ``# nocheck: cache-read``;
case-insensitive) on the call's own line OR, for multi-line calls, on
any line spanned by the call expression. Use this for legitimate
exceptions — e.g. reading a file from a tempdir created at runtime, a
file outside the project tree, or a synthetic fixture written and
read back inside the same test. Do NOT use it to silence the lint for
"I want the convenience of ``path.read_text()``" — replace with
``read_text(str(path))`` from ``utils.cache.files`` instead.

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

_RULE = "cache-read"
_SCAN_PREFIXES: tuple[str, ...] = (
    "tests/",
    "utils/",
    "cli/",
    "plugins/",
    "library/",
)
# ``utils/cache/`` IS the cache implementation; routing it through itself
# would create a circular dependency.
_SKIP_PREFIXES: tuple[str, ...] = ("utils/cache/",)
_FORBIDDEN_ATTRS: frozenset[str] = frozenset({"read_text", "read_bytes"})


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
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in _FORBIDDEN_ATTRS:
            continue
        if _is_noqa(node):
            continue
        findings.append(
            Finding(
                file=path,
                line=node.lineno,
                pattern=f".{func.attr}(...)",
                snippet=_snippet(node),
            )
        )
    return findings


class TestNoUncachedFileReads(unittest.TestCase):
    def test_modules_in_scope_use_cached_read_text(self) -> None:
        """Forbidden ``Path.read_text`` / ``Path.read_bytes`` calls in
        in-scope code without an explicit ``# nocheck: cache-read``
        marker. Use :func:`utils.cache.files.read_text` so the LRU
        cache is shared across the pytest session.
        """
        repo_root = PROJECT_ROOT

        findings: list[Finding] = []
        for path_str in iter_project_files(extensions=(".py",)):
            rel = Path(path_str).relative_to(repo_root).as_posix()
            if not rel.startswith(_SCAN_PREFIXES):
                continue
            if rel.startswith(_SKIP_PREFIXES):
                continue
            findings.extend(_scan_file(Path(path_str)))

        if findings:
            formatted = "\n".join(f.format(repo_root) for f in findings)
            self.fail(
                f"{len(findings)} uncached file-read call(s) under "
                f"{_SCAN_PREFIXES}:\n{formatted}\n\n"
                "FIX: replace with `read_text` from "
                "`utils.cache.files`:\n\n"
                "    from utils.cache.files import read_text\n"
                "    text = read_text(str(path))\n\n"
                "This shares one decoded read per file across the whole "
                "pytest session. See docs/agents/action/testing.md.\n\n"
                "Only opt out per call with `# nocheck: cache-read` when "
                "the read is genuinely outside the project tree "
                "(tempdirs, synthetic fixtures written inside the same "
                "test, files mutated in the same flow that re-reads "
                "them, etc.) and a short inline comment explains why."
            )


if __name__ == "__main__":
    unittest.main()
