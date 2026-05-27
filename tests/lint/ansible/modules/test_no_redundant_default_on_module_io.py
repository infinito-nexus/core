"""Forbid `<reg>.stdout|stderr|rc | default(...)` inside same-task conditionals.

Ansible's `command:`, `shell:`, `raw:`, and similar modules always populate
`stdout`, `stderr`, and `rc` on a successful return. Same-task
conditionals (`changed_when:`, `failed_when:`, `until:`) only run when
the module actually executed, so any `| default(...)` filter on those
attributes is dead code: the fallback can never fire.

Removing the filter shortens the conditional and makes the contract
clearer. Cross-task references (a later task reading the registered
result of an earlier task that may have been skipped) are out of scope
and remain a legitimate use of `| default(...)`.
"""

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

SCAN_DIRS = ("roles", "tasks", "playbooks")
_SCAN_PREFIXES = tuple(f"{d}/" for d in SCAN_DIRS)
SCAN_SUFFIXES = (".yml", ".yaml")

# Same-task conditional keys whose body sees a freshly-set module result.
_CONDITIONAL_KEYS = ("changed_when", "failed_when", "until")
_CONDITIONAL_LINE_RE = re.compile(
    rf"""^\s*(?:-\s+)?(?:{"|".join(_CONDITIONAL_KEYS)})\s*:""",
)

# Match `<word>.<stdout|stderr|rc> | default(` with optional whitespace.
_REDUNDANT_DEFAULT_RE = re.compile(
    r"""
    \.                                  # attribute access on a registered var
    (?P<attr>stdout|stderr|rc)          # module-set fields
    \s*\|\s*default\s*\(                # the redundant filter call
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    attr: str
    snippet: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return f"{rel}:{self.line}: `.{self.attr} | default(...)` — {self.snippet}"


def _iter_target_files(repo_root: Path) -> Iterable[Path]:
    for abs_path in iter_project_files(extensions=SCAN_SUFFIXES):
        rel = Path(abs_path).relative_to(repo_root).as_posix()
        if any(rel.startswith(p) for p in _SCAN_PREFIXES):
            yield Path(abs_path)


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings

    for idx, line in enumerate(text.splitlines(), start=1):
        if not _CONDITIONAL_LINE_RE.match(line):
            continue
        findings.extend(
            Finding(file=path, line=idx, attr=m.group("attr"), snippet=line.strip())
            for m in _REDUNDANT_DEFAULT_RE.finditer(line)
        )
    return findings


class TestNoRedundantDefaultOnModuleIO(unittest.TestCase):
    def test_no_default_filter_on_module_io_in_same_task_conditionals(self) -> None:
        """`<reg>.stdout|stderr|rc | default(...)` inside `changed_when:` /
        `failed_when:` / `until:` is dead code.

        The module always runs before its own conditional fires, so the
        filter never has anything to fall back to. Drop the filter::

            changed_when: "'CHANGED' in result.stdout"

        instead of::

            changed_when: "'CHANGED' in (result.stdout | default(''))"
        """
        findings: list[Finding] = []
        for path in _iter_target_files(PROJECT_ROOT):
            findings.extend(_scan_file(path))

        if findings:
            formatted = "\n".join(f.format(PROJECT_ROOT) for f in findings)
            self.fail(
                f"Found {len(findings)} redundant `| default(...)` "
                f"call(s) on module-set attributes inside same-task "
                f"conditionals ({', '.join(_CONDITIONAL_KEYS)}):\n"
                f"{formatted}\n\n"
                "Remove the filter — the attribute is always set when "
                "the conditional runs."
            )


if __name__ == "__main__":
    unittest.main()
