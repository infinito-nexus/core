"""Every `make <target>` invocation in scripts, the Makefile, and CI
workflows must reference a target defined in the project Makefile.

Catches refactoring drift such as renaming `up`/`down` to `compose-up`/
`compose-down` without updating callers, and missing-space typos like
``make compose-deploymode=…`` (intended ``make compose-deploy mode=…``).

Scope: shell scripts (`*.sh`), the root Makefile (`$(MAKE) …` recursive
calls), and GitHub workflow YAML. Whole-line comments and matches inside
single/double-quoted strings (``echo "make X"``) are skipped — they are
prose, not invocations.

Suppress a line with a trailing ``# nocheck:make-target`` comment when the
match is intentional (e.g. invoking a target from a *different* Makefile via
``make -C <dir>``)."""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_TARGET_DEF_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_-]*)\s*:(?!=)")
_PHONY_RE = re.compile(r"^\.PHONY\s*:\s*(?P<names>.+?)\s*$")

# Match a `make` invocation and capture the first lowercase kebab-case token
# after it (the candidate target). Skips an optional `-C <dir>` argument.
# The preceding context must be a line start or a shell separator so we do not
# match the word "make" embedded in identifiers.
_MAKE_INVOCATION_RE = re.compile(
    r"""
    (?:^|[\s;&|`(])              # start-of-line or shell word boundary
    make\b                       # the make binary (case-sensitive)
    (?:\s+-C\s+\S+)?             # optional -C <dir>
    \s+
    (?P<target>[a-z][a-z0-9_-]*) # first kebab-case token
    """,
    re.VERBOSE,
)

# Match $(MAKE) / ${MAKE} (optionally quoted) recursive invocations inside the
# Makefile, capturing the candidate target the same way.
_RECURSIVE_MAKE_RE = re.compile(
    r"""
    "?\$[\(\{]MAKE[\)\}]"?       # $(MAKE), ${MAKE}, "$(MAKE)", "${MAKE}"
    (?:\s+-C\s+\S+)?
    \s+
    (?P<target>[a-z][a-z0-9_-]*)
    """,
    re.VERBOSE,
)

_NOCHECK_MARKER = "nocheck:make-target"
_COMMENT_LINE_RE = re.compile(r"^\s*#")


@dataclass(frozen=True)
class _Reference:
    path: str
    line_no: int
    target: str
    snippet: str


def _inside_string_literal(line: str, position: int) -> bool:
    """True if *position* in *line* sits inside an unclosed ``'`` or ``"``
    quote opened earlier on the same line. Used to skip ``echo "… make X …"``
    occurrences where ``make`` is part of a literal string, not an invocation."""
    prefix = line[:position]
    return prefix.count('"') % 2 == 1 or prefix.count("'") % 2 == 1


def _project_targets(makefile: Path) -> set[str]:
    targets: set[str] = set()
    for line in read_text(str(makefile)).splitlines():
        match = _TARGET_DEF_RE.match(line)
        if match is not None:
            targets.add(match.group("name"))
            continue
        phony = _PHONY_RE.match(line)
        if phony is not None:
            targets.update(phony.group("names").split())
    return targets


def _scan_line(line: str, regex: re.Pattern[str]) -> list[tuple[str, str]]:
    if _NOCHECK_MARKER in line:
        return []
    if _COMMENT_LINE_RE.match(line):
        return []
    out: list[tuple[str, str]] = []
    for match in regex.finditer(line):
        if _inside_string_literal(line, match.start("target")):
            continue
        out.append((match.group("target"), line.strip()))
    return out


def _scan_file(path: Path, regex: re.Pattern[str]) -> list[_Reference]:
    try:
        content = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    rel = str(path.relative_to(PROJECT_ROOT))
    out: list[_Reference] = []
    for index, line in enumerate(content.splitlines(), start=1):
        for target, snippet in _scan_line(line, regex):
            out.append(_Reference(rel, index, target, snippet))
    return out


def _candidate_files() -> list[Path]:
    paths: list[Path] = [PROJECT_ROOT / "Makefile"]
    paths.extend(Path(raw) for raw in iter_project_files(extensions=(".sh",)))
    workflows_dir = PROJECT_ROOT / ".github" / "workflows"
    if workflows_dir.is_dir():
        paths.extend(sorted(workflows_dir.glob("*.yml")))
        paths.extend(sorted(workflows_dir.glob("*.yaml")))
    return paths


class TestMakeReferencesResolve(unittest.TestCase):
    def setUp(self) -> None:
        self.makefile = PROJECT_ROOT / "Makefile"
        self.assertTrue(self.makefile.is_file(), "Makefile not found at project root")
        self.targets = _project_targets(self.makefile)
        self.assertTrue(self.targets, "no targets parsed from Makefile")

    def test_every_referenced_target_is_defined(self) -> None:
        references: list[_Reference] = []
        for path in _candidate_files():
            regex = (
                _RECURSIVE_MAKE_RE if path.name == "Makefile" else _MAKE_INVOCATION_RE
            )
            references.extend(_scan_file(path, regex))

        unknown = [ref for ref in references if ref.target not in self.targets]
        if not unknown:
            return

        lines = [
            f"{len(unknown)} `make <target>` invocation(s) reference a "
            "target that is not defined in the Makefile:",
            "",
        ]
        lines.extend(
            f"  {ref.path}:{ref.line_no}: '{ref.target}'  ->  {ref.snippet}"
            for ref in unknown
        )
        lines.extend(
            [
                "",
                "Fix the typo / rename, or — if the reference is intentional "
                "(e.g. `make -C <other-dir> <target>`) — append "
                f"`# {_NOCHECK_MARKER}` to suppress the check on that line.",
            ]
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
