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

_JINJA_EXPR_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_JINJA_STMT_RE = re.compile(r"\{%(.*?)%\}", re.DOTALL)
_RAW_BLOCK_RE = re.compile(
    r"\{%\s*-?\s*raw\s*-?\s*%\}.*?\{%\s*-?\s*endraw\s*-?\s*%\}",
    re.DOTALL,
)
_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)
_STR_LITERAL_RE = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
_DOTTED_TOKEN_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b")
_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*dotted-path")


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    path: str
    missing_at: str
    snippet: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return (
            f"{rel}:{self.line}: '{self.path}' -> missing key "
            f"'{self.missing_at}' in dict tree; {self.snippet}"
        )


def _load_group_vars_namespace() -> dict[str, Any]:
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


def _load_role_namespace(role_dir: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for sub in ("vars", "defaults"):
        f = role_dir / sub / "main.yml"
        if not f.exists():
            continue
        try:
            data = load_yaml_any(str(f))
        except Exception as exc:
            logger.debug("Skipping role var file %s: %s", f, exc)
            continue
        if isinstance(data, dict):
            merged.update(data)
    return merged


def _current_role_namespace(
    path: Path, role_namespaces: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    try:
        rel = path.relative_to(ROLES_DIR)
    except ValueError:
        return {}
    parts = rel.parts
    if not parts:
        return {}
    return role_namespaces.get(parts[0], {})


def _walk_path(root: Any, segments: list[str]) -> tuple[bool, str | None, bool]:
    """Walk ``segments`` through ``root``.

    Returns ``(resolved, missing_at, opaque)``:
        * ``resolved`` is True when every segment maps to a key in a dict.
        * ``missing_at`` is the first segment that failed to resolve while
          the parent was still a dict (definitively broken path).
        * ``opaque`` is True when traversal hit a non-dict node before
          consuming all segments — the runtime shape is unknown statically
          and callers MUST NOT flag.
    """
    node: Any = root
    for seg in segments:
        if isinstance(node, dict):
            if seg in node:
                node = node[seg]
                continue
            return False, seg, False
        return False, None, True
    return True, None, False


def _mask_length_preserving(pattern: re.Pattern, text: str) -> str:
    def _spaces(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    return pattern.sub(_spaces, text)


def _scan_block_expr(
    expr: str,
    block_offset: int,
    line_of: callable,
    text_lines: list[str],
    group_vars: dict[str, Any],
    role_ns: dict[str, Any],
    path: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    expr_clean = _STR_LITERAL_RE.sub(lambda m: " " * len(m.group(0)), expr)

    for m_token in _DOTTED_TOKEN_RE.finditer(expr_clean):
        dotted = m_token.group(1)
        segments = dotted.split(".")
        head_id = segments[0]
        rest = segments[1:]

        # Skip tokens immediately followed by call or subscript: the access
        # shape would have to be evaluated at runtime.
        i = m_token.end()
        while i < len(expr_clean) and expr_clean[i].isspace():
            i += 1
        if i < len(expr_clean) and expr_clean[i] in "([":
            continue

        # group_vars wins over role-local on conflict (group_vars is always
        # loaded; role vars are loaded only when the role is in the play).
        if head_id in group_vars:
            root = group_vars[head_id]
        elif head_id in role_ns:
            root = role_ns[head_id]
        else:
            # Unknown head — runtime / loop / register / macro / caller var.
            # Out of scope here; covered by test_variable_definitions.py for
            # the existence-of-top-level-identifier check.
            continue

        resolved, missing_at, opaque = _walk_path(root, rest)
        if resolved or opaque:
            continue

        line_no = line_of(block_offset + m_token.start())
        snippet_line = (
            text_lines[line_no - 1].strip()
            if 0 <= line_no - 1 < len(text_lines)
            else ""
        )
        if _NOCHECK_RE.search(snippet_line):
            continue

        findings.append(
            Finding(
                file=path,
                line=line_no,
                path=dotted,
                missing_at=missing_at or "(unknown)",
                snippet=snippet_line,
            )
        )

    return findings


def _scan_file(
    path: Path,
    group_vars: dict[str, Any],
    role_ns: dict[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings

    masked = _mask_length_preserving(_RAW_BLOCK_RE, text)
    masked = _mask_length_preserving(_JINJA_COMMENT_RE, masked)
    text_lines = text.splitlines()

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

    for block in _JINJA_EXPR_RE.finditer(masked):
        findings.extend(
            _scan_block_expr(
                block.group(1),
                block.start(1),
                _line_of,
                text_lines,
                group_vars,
                role_ns,
                path,
            )
        )
    for block in _JINJA_STMT_RE.finditer(masked):
        findings.extend(
            _scan_block_expr(
                block.group(1),
                block.start(1),
                _line_of,
                text_lines,
                group_vars,
                role_ns,
                path,
            )
        )
    return findings


def _iter_target_files() -> list[Path]:
    scan_prefix = tuple(str(PROJECT_ROOT / d) + "/" for d in SCAN_DIRS)
    return [
        Path(abs_path)
        for abs_path in iter_project_files(extensions=SCAN_SUFFIXES, exclude_tests=True)
        if abs_path.startswith(scan_prefix)
    ]


class TestDottedPathKeysExist(unittest.TestCase):
    """Forbid Jinja dotted paths whose head resolves via
    ``group_vars/all/*.yml`` or the consuming role's own ``vars/main.yml``
    / ``defaults/main.yml`` but whose deeper segments do NOT exist as keys
    in that dict tree.

    Catches the bug class where a dotted reference looks plausible but
    references a key that was renamed, removed, or never existed —
    exactly the regression that previously lived in
    ``roles/web-app-odoo/vars/main.yml`` with ``LDAP.SERVER.REACH_DOMAIN``
    (canonical path: ``LDAP.SERVER.DOMAIN``).

    Scope rules:

    * **Only pure dotted paths** (``FOO.BAR`` or deeper) are validated.
      Tokens whose tail is immediately followed by ``(`` (function call)
      or ``[`` (dynamic subscript) are skipped — the access shape would
      have to be evaluated at runtime.
    * **Single identifiers** without a dot are out of scope here; their
      definedness is enforced by
      ``tests/integration/jinja/test_variable_definitions.py``.
    * **Unknown heads** (loop vars, registers, macro params, caller-injected
      vars) are out of scope: they may legitimately resolve at runtime.
    * **Opaque paths** (a segment in the dict tree is a templated string or
      a scalar rather than a sub-dict) cannot be introspected statically
      and are NOT flagged.
    * **Per-line opt-out:** ``# nocheck: dotted-path`` plus a one-line
      rationale.
    """

    def test_dotted_paths_resolve(self) -> None:
        group_vars = _load_group_vars_namespace()
        role_namespaces: dict[str, dict[str, Any]] = {}
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            ns = _load_role_namespace(role_dir)
            if ns:
                role_namespaces[role_dir.name] = ns

        findings: list[Finding] = []
        for path in _iter_target_files():
            role_ns = _current_role_namespace(path, role_namespaces)
            findings.extend(_scan_file(path, group_vars, role_ns))

        if findings:
            formatted = "\n".join(f.format(PROJECT_ROOT) for f in findings)
            self.fail(
                "Found Jinja dotted paths whose head resolves via "
                "group_vars/all/ or the consuming role's vars/defaults, "
                "but the deeper segments do not exist as keys in that "
                "dict tree. Either correct the path to the canonical key "
                "or add the missing key to the SPOT. Annotate the line "
                "with `# nocheck: dotted-path` and a one-line rationale "
                "to suppress.\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
