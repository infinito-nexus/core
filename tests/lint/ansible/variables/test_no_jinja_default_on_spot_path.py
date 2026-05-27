from __future__ import annotations

import logging
import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

logger = logging.getLogger(__name__)

SCAN_DIRS = ("roles", "tasks", "group_vars")
SCAN_SUFFIXES = (".yml", ".yaml", ".j2")

ROLES_DIR = PROJECT_ROOT / "roles"
GROUP_VARS_ALL = PROJECT_ROOT / "group_vars" / "all"

_JINJA_BLOCK_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_RAW_BLOCK_RE = re.compile(
    r"\{%\s*-?\s*raw\s*-?\s*%\}.*?\{%\s*-?\s*endraw\s*-?\s*%\}",
    re.DOTALL,
)
_LEADING_PATH_RE = re.compile(r"^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")
_DEFAULT_FILTER_RE = re.compile(r"\|\s*default\s*\(")
_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*spot-default")


def _find_default_target(expr: str, pipe_pos: int) -> str | None:
    """Return the sub-expression that ``| default(...)`` is applied to.

    ``pipe_pos`` is the index of the ``|`` character of the matched
    ``| default(`` occurrence inside ``expr``. The function walks left
    from ``pipe_pos - 1``, tracking parenthesis nesting, and stops at the
    first delimiter (``|``, ``,``, unmatched ``(``) at depth 0, or at the
    start of ``expr``. Returns the trimmed text between that stop and
    the pipe, or ``None`` if the slice is empty.
    """
    i = pipe_pos - 1
    while i >= 0 and expr[i].isspace():
        i -= 1
    end = i
    depth = 0
    while i >= 0:
        c = expr[i]
        if c == ")":
            depth += 1
        elif c == "(":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and c in ("|", ","):
            break
        i -= 1
    start = i + 1
    target = expr[start : end + 1].strip()
    return target or None


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    path: str
    snippet: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return f"{rel}:{self.line}: '{self.path}' -> {self.snippet}"


def _load_group_vars_namespace() -> dict[str, Any]:
    """Merge every top-level key from ``group_vars/all/*.yml`` into one dict.

    Only ``group_vars/all/`` is treated as SPOT here: those keys are loaded
    unconditionally on every play, so a Jinja ``| default(...)`` against
    them is provably dead code or silent SPOT decoupling.

    Role-level ``vars/main.yml`` and ``defaults/main.yml`` are NOT folded in:
    Ansible only loads them when the owning role is in the play, so a
    ``| default(...)`` on a key declared in another role is a legitimate
    caller-injection guard, not a SPOT violation.
    """
    group_vars: dict[str, Any] = {}
    for gv in sorted(GROUP_VARS_ALL.glob("*.yml")):
        try:
            data = load_yaml_any(str(gv))
        except Exception as exc:
            logger.debug("Skipping group_vars file %s: %s", gv, exc)
            continue
        if isinstance(data, dict):
            group_vars.update(data)
    return group_vars


def _walk_path(root: Any, segments: list[str]) -> tuple[bool, bool]:
    """Walk dotted ``segments`` through ``root``.

    Returns ``(resolved, opaque)``:
        * ``resolved`` is True when every segment maps to a key in a dict
          (the leaf may be a scalar / templated string / sub-dict — only
          existence matters for SPOT purposes).
        * ``opaque`` is True when traversal hit a non-dict node before
          consuming all segments (e.g. a templated string whose runtime
          shape we cannot introspect statically). Callers MUST NOT flag
          opaque resolutions.
    """
    node: Any = root
    for seg in segments:
        if isinstance(node, dict):
            if seg in node:
                node = node[seg]
                continue
            return False, False
        return False, True
    return True, False


def _iter_target_files() -> list[Path]:
    scan_prefix = tuple(str(PROJECT_ROOT / d) + "/" for d in SCAN_DIRS)
    return [
        Path(abs_path)
        for abs_path in iter_project_files(extensions=SCAN_SUFFIXES, exclude_tests=True)
        if abs_path.startswith(scan_prefix)
    ]


def _scan_file(
    path: Path,
    group_vars: dict[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings

    # Mask {% raw %}...{% endraw %} so demo snippets in documentation don't
    # generate false positives.
    def _mask(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    masked = _RAW_BLOCK_RE.sub(_mask, text)
    text_lines = text.splitlines()

    # Precompute newline offsets so we can resolve an offset to a 1-based line.
    line_starts: list[int] = [0]
    for i, ch in enumerate(masked):
        if ch == "\n":
            line_starts.append(i + 1)

    def _line_of(offset: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    for block in _JINJA_BLOCK_RE.finditer(masked):
        expr = block.group(1)
        block_offset = block.start(1)
        for m_default in _DEFAULT_FILTER_RE.finditer(expr):
            target = _find_default_target(expr, m_default.start())
            if target is None:
                continue
            # Strip a single layer of outer parentheses so
            # ``(FOO.BAR) | default(..)`` is still treated as a pure path
            # access. Deeper nesting / mixed operators are intentionally
            # left alone below by the trailing-text guard.
            if target.startswith("(") and target.endswith(")"):
                target = target[1:-1].strip()

            m_path = _LEADING_PATH_RE.match(target)
            if not m_path:
                continue
            # The leading dotted path must be the ENTIRE target expression.
            # Subscripts ``[...]``, function calls ``(...)``, operators,
            # and inline conditionals all leave trailing text and disqualify
            # the match — we cannot reason about non-static access shapes.
            if target[m_path.end() :].strip():
                continue

            dotted = m_path.group(1)
            segments = dotted.split(".")
            head_id = segments[0]
            rest = segments[1:]

            line_no = _line_of(block_offset + m_default.start())
            snippet_line = (
                text_lines[line_no - 1].strip() if line_no - 1 < len(text_lines) else ""
            )

            if _NOCHECK_RE.search(snippet_line):
                continue

            if head_id not in group_vars:
                continue
            resolved, _opaque = _walk_path(group_vars[head_id], rest)
            if resolved:
                findings.append(
                    Finding(file=path, line=line_no, path=dotted, snippet=snippet_line)
                )

    return findings


class TestNoJinjaDefaultOnSpotPath(unittest.TestCase):
    """Forbid ``| default(...)`` on Jinja expressions whose path resolves via
    ``group_vars/all/*.yml`` — the project-wide unconditionally-loaded SPOT.

    When a path resolves through ``group_vars/all/`` the value is provably
    defined at runtime, so the Jinja ``default(...)`` filter never fires and
    is at best dead code, at worst a silent SPOT decoupling that masks any
    future change to the canonical value.

    Role-level ``vars/main.yml`` and ``defaults/main.yml`` are intentionally
    NOT folded into this check: Ansible only loads them when the owning role
    is part of the play, so a ``| default(...)`` against a key declared in
    another role is a legitimate caller-injection guard, not a SPOT
    violation. Hoist a var into ``group_vars/all/`` if you want SPOT
    enforcement on it.

    Suppress a single line with ``# nocheck: spot-default`` plus a one-line
    rationale.
    """

    def test_no_default_on_spot_path(self) -> None:
        group_vars = _load_group_vars_namespace()
        findings: list[Finding] = []
        for path in _iter_target_files():
            findings.extend(_scan_file(path, group_vars))

        if findings:
            formatted = "\n".join(f.format(PROJECT_ROOT) for f in findings)
            self.fail(
                "Found `| default(...)` on Jinja paths whose head resolves "
                "via `group_vars/all/`. Those keys are loaded "
                "unconditionally, so the default never fires and silently "
                "masks the SPOT value when it changes. Drop the default, "
                "or annotate the line with `# nocheck: spot-default` and a "
                "one-line rationale.\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
