from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable

SCAN_DIRS = ("roles", "tasks", "group_vars")
_SCAN_PREFIXES = tuple(f"{d}/" for d in SCAN_DIRS)
SCAN_SUFFIXES = (".yml", ".yaml", ".j2")

# Match the start of a `lookup('config', ...)` / `lookup("config", ...)` call.
# The opening paren and arg parsing are handled procedurally below so that
# nested parens, embedded strings, and trailing filter pipelines are tracked
# correctly.
_LOOKUP_CONFIG_RE = re.compile(r"""lookup\(\s*['"]config['"]""")
_DEFAULT_FILTER_RE = re.compile(r"\|\s*default\s*\(")


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    snippet: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return f"{rel}:{self.line}: {self.snippet}"


def _iter_target_files(repo_root: Path) -> Iterable[Path]:
    for abs_path in iter_project_files(extensions=SCAN_SUFFIXES):
        rel = Path(abs_path).relative_to(repo_root).as_posix()
        if any(rel.startswith(p) for p in _SCAN_PREFIXES):
            yield Path(abs_path)


def _walk_lookup_call(line: str, lookup_match_start: int) -> tuple[int, int]:
    """Return ``(close_paren_index, top_level_comma_count)`` for the lookup call
    starting at ``lookup_match_start``. Returns ``(-1, -1)`` if the call does
    not close on the same line (multi-line calls are skipped — the lint is
    intentionally line-local).
    """
    open_paren = line.find("(", lookup_match_start)
    if open_paren < 0:
        return (-1, -1)

    depth = 0
    commas = 0
    in_str: str | None = None
    i = open_paren
    while i < len(line):
        c = line[i]
        if in_str is not None:
            # Tolerate backslash-escapes; Jinja string literals rarely use them
            # but the loss is at worst a missed lint for an exotic edge case.
            if c == in_str and line[i - 1] != "\\":
                in_str = None
        elif c in ("'", '"'):
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return (i, commas)
        elif c == "," and depth == 1:
            commas += 1
        i += 1
    return (-1, -1)


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings

    for idx, line in enumerate(text.splitlines(), start=1):
        for m in _LOOKUP_CONFIG_RE.finditer(line):
            close_paren, commas = _walk_lookup_call(line, m.start())
            if close_paren < 0:
                continue
            # The plugin signature is lookup('config', application_id,
            # config_path[, default]). With exactly 2 top-level commas the
            # call has 3 args ('config', app, path) and no plugin default,
            # so a missing key raises AnsibleError before any Jinja filter
            # downstream can fire.
            if commas != 2:
                continue
            tail = line[close_paren + 1 :]
            if _DEFAULT_FILTER_RE.search(tail):
                findings.append(Finding(file=path, line=idx, snippet=line.strip()))
                break  # one finding per line is enough
    return findings


class TestNoLookupConfigJinjaDefault(unittest.TestCase):
    def test_default_must_be_passed_as_third_lookup_arg(self) -> None:
        """`lookup('config', app, path) | default(X)` is dead-code.

        The project's `config` lookup (plugins/lookup/config.py) raises
        AnsibleError on a missing key when called with only 2 terms. The
        Jinja `| default(...)` filter only fires on Jinja `Undefined`, which
        the lookup never produces — it either returns a value or raises.
        Pass the fallback as the third lookup argument so it actually
        applies::

            lookup('config', application_id, 'services.ldap.enabled', true)

        instead of::

            lookup('config', application_id, 'services.ldap.enabled') | default(true)
        """
        findings: list[Finding] = []
        for path in _iter_target_files(PROJECT_ROOT):
            findings.extend(_scan_file(path))

        if findings:
            formatted = "\n".join(f.format(PROJECT_ROOT) for f in findings)
            self.fail(
                "Found `lookup('config', ...)` paired with `| default(...)`. "
                "The 2-term lookup raises on missing keys, so the Jinja "
                "default never fires. Pass the fallback as the 3rd lookup "
                "arg instead:\n"
                "    lookup('config', app, 'a.b', <default>)\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
