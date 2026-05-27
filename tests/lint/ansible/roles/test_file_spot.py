"""Lint guard: every ``.py`` file MUST reference role-relative paths via
the ``ROLE_FILE_*`` constants in :mod:`utils.roles.mapping` instead of
hard-coding the path string in any form.

Background
==========
:mod:`utils.roles.mapping` carries the role-file vocabulary
(``ROLE_FILE_META_MAIN``, ``ROLE_FILE_VARS_MAIN``, …) plus the per-type
``mandatory`` / ``allowed`` / ``marker`` policy in :data:`ROLE_FILES`.
Code that joins, compares, or merges role files MUST import the constant
so a future rename (e.g. ``meta/services.yml`` → ``meta/compose.yml``)
propagates from one edit. Hard-coded literals
(``"meta/services.yml"``, ``role_dir / "meta" / "services.yml"``,
``os.path.join(role, "meta", "services.yml")``,
``f"{role}/meta/main.yml"``) bypass the schema and make the SPOT load-
bearing only by convention.

Detection
=========
AST-walks every ``.py`` file under the production trees (``utils/``,
``cli/``, ``plugins/``, ``filter_plugins/``, ``lookup_plugins/``,
``roles/``, ``scripts/``, ``tasks/``) AND under ``tests/`` and flags the
following composite forms whenever the value (or the joined value)
matches a ``ROLE_FILE_*`` constant:

* a standalone string constant (``"meta/services.yml"``);
* an f-string segment that contains a flag literal as a path tail
  (``f"{role}/meta/main.yml"`` carries the constant ``"/meta/main.yml"``);
* a pathlib ``/`` chain whose trailing string operands join to a flag
  literal (``role_dir / "meta" / "services.yml"``);
* a ``+`` concatenation chain whose trailing string operands join to a
  flag literal (``prefix + "meta/" + "main.yml"``);
* an ``os.path.join`` / ``posixpath.join`` / ``Path.joinpath`` call
  whose trailing string positional arguments join to a flag literal.

A match in any form requires at least two adjacent literal segments for
the chain forms so a single literal like ``role_dir / "meta/main.yml"``
is reported once (by the standalone-constant pass) instead of twice.

The exact flag set is auto-discovered from
:mod:`utils.roles.mapping` so adding a new ``ROLE_FILE_*`` constant
extends coverage with zero further edits. ``ROLE_FILE_README`` is
exempt because ``README.md`` is too generic to flag without context.

Allowed
=======
* ``utils/roles/mapping.py``: defines the constants. Hard-coded
  literals there are the SPOT itself.
* Per-line ``# nocheck: role-file-spot`` (``same-or-above`` placement)
  for legitimate exceptions; e.g. tests that assert a literal value of
  the constant, migration scripts that operate on raw paths, doc
  comments embedding the path string.

Caching
=======
File contents are routed through :func:`utils.cache.files.read_text`
so multiple lint tests scanning the same source pay one read.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import utils.roles.mapping as _mapping
from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

_RULE = "role-file-spot"

# README.md is too generic to flag without context (the project ships
# many README files unrelated to roles). Every other ROLE_FILE_*
# constant is project-specific enough to flag.
_EXEMPT_CONSTANT_NAMES: frozenset[str] = frozenset({"ROLE_FILE_README"})


def _build_literal_to_constant() -> dict[str, str]:
    """Return ``{literal_value: constant_name}`` for every ROLE_FILE_*
    constant in :mod:`utils.roles.mapping`, except the exempt ones.
    """
    out: dict[str, str] = {}
    for name, value in vars(_mapping).items():
        if not name.startswith("ROLE_FILE_"):
            continue
        if name in _EXEMPT_CONSTANT_NAMES:
            continue
        if not isinstance(value, str):
            continue
        out[value] = name
    return out


_LITERAL_TO_CONSTANT: dict[str, str] = _build_literal_to_constant()

# Files that legitimately hold the literal values:
# * ``utils/roles/mapping.py`` defines the constants.
_EXEMPT_FILES: frozenset[Path] = frozenset(
    {
        PROJECT_ROOT / "utils" / "roles" / "mapping.py",
    }
)

_SCAN_DIRS: frozenset[str] = frozenset(
    {
        "utils",
        "cli",
        "plugins",
        "filter_plugins",
        "lookup_plugins",
        "roles",
        "scripts",
        "tasks",
        "tests",
    }
)


def _flag_match(value: str) -> str | None:
    """Return the matching ``ROLE_FILE_*`` constant name when *value*
    equals a flag literal, ends with ``/<flag>``, starts with
    ``<flag>/``, or contains ``/<flag>/`` as a path segment.
    """
    if value in _LITERAL_TO_CONSTANT:
        return _LITERAL_TO_CONSTANT[value]
    for flag, name in _LITERAL_TO_CONSTANT.items():
        if value.endswith("/" + flag):
            return name
        if value.startswith(flag + "/"):
            return name
        if "/" + flag + "/" in value:
            return name
    return None


def _trailing_string_div_chain(node: ast.AST) -> list[str]:
    """Return the trailing string-constant operands of a ``/`` chain
    (innermost first). Empty when the chain is broken before any
    string constant or *node* is not a ``BinOp(Div)``.
    """
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
        right = cur.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            parts.append(right.value)
            cur = cur.left
        else:
            break
    return parts


def _trailing_string_add_chain(node: ast.AST) -> list[str]:
    """Same as :func:`_trailing_string_div_chain`, but for ``+``
    concatenation chains.
    """
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Add):
        right = cur.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            parts.append(right.value)
            cur = cur.left
        else:
            break
    return parts


def _is_path_join_call(node: ast.Call) -> bool:
    """Return ``True`` when *node* is ``os.path.join``,
    ``posixpath.join``, ``ntpath.join``, or any ``.joinpath(...)``
    call. ``str.join`` and similar non-path joins return ``False``.
    """
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr == "joinpath":
        return True
    if func.attr != "join":
        return False
    recv = func.value
    if isinstance(recv, ast.Attribute) and recv.attr == "path":
        inner = recv.value
        return isinstance(inner, ast.Name) and inner.id == "os"
    return isinstance(recv, ast.Name) and recv.id in {"posixpath", "ntpath"}


def _trailing_string_call_args(node: ast.Call) -> list[str]:
    """Return the trailing string-constant positional arguments of
    *node* (innermost first), stopping at the first non-string arg.
    """
    parts: list[str] = []
    for arg in reversed(node.args):
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            parts.append(arg.value)
        else:
            break
    return parts


def _check_div_chain(node: ast.AST) -> str | None:
    parts = _trailing_string_div_chain(node)
    if len(parts) < 2:
        return None
    return _flag_match("/".join(reversed(parts)))


def _check_add_chain(node: ast.AST) -> str | None:
    parts = _trailing_string_add_chain(node)
    if len(parts) < 2:
        return None
    return _flag_match("".join(reversed(parts)))


def _check_call_join(node: ast.Call) -> str | None:
    if not _is_path_join_call(node):
        return None
    parts = _trailing_string_call_args(node)
    if len(parts) < 2:
        return None
    return _flag_match("/".join(reversed(parts)))


def _file_offenders(path: Path) -> list[str]:
    """Return ``[]`` if the file uses the SPOT throughout, or a list of
    human-readable ``line N: <kind> should use ROLE_FILE_<NAME>``
    strings for every flagged occurrence.
    """
    try:
        src = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    lines = src.splitlines()
    seen: set[tuple[int, str, str]] = set()
    offenders: list[str] = []

    def _record(line_no: int, kind: str, name: str, detail: str) -> None:
        key = (line_no, kind, name)
        if key in seen:
            return
        if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
            return
        seen.add(key)
        offenders.append(f"line {line_no}: {detail} should use {name}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            name = _flag_match(node.value)
            if name is not None:
                _record(node.lineno, "literal", name, f'"{node.value}"')
            continue

        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Div):
                name = _check_div_chain(node)
                if name is not None:
                    _record(node.lineno, "div-chain", name, "pathlib `/` chain")
                continue
            if isinstance(node.op, ast.Add):
                name = _check_add_chain(node)
                if name is not None:
                    _record(node.lineno, "add-chain", name, "string `+` concat")
                continue

        if isinstance(node, ast.Call):
            name = _check_call_join(node)
            if name is not None:
                _record(node.lineno, "call-join", name, "path-join call")
            continue

    offenders.sort(key=lambda msg: int(msg.split(":", 1)[0].split()[-1]))
    return offenders


def _scan_paths() -> list[Path]:
    """Iterate every production .py file via the shared file-walk cache."""
    out: list[Path] = []
    for s in iter_project_files(extensions=(".py",), exclude_tests=False):
        p = Path(s)
        try:
            rel = p.relative_to(PROJECT_ROOT)
        except ValueError:
            continue
        if not rel.parts or rel.parts[0] not in _SCAN_DIRS:
            continue
        if p in _EXEMPT_FILES:
            continue
        out.append(p)
    return sorted(out)


class TestRoleFileSpot(unittest.TestCase):
    """Every .py file MUST reference role files via the ROLE_FILE_*
    constants in utils.roles.mapping instead of hard-coded literals."""

    def test_role_files_are_referenced_via_spot(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _scan_paths():
            issues = _file_offenders(path)
            if issues:
                offenders[path] = issues

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [
            f"{len(offenders)} .py file(s) hard-code a role-file path "
            f"instead of importing the matching ROLE_FILE_* constant from "
            f"utils.roles.mapping (the SPOT):",
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            lines.extend(f"      * {issue}" for issue in issues)
        lines.append("")
        lines.append(
            "Fix: import the constant from utils.roles.mapping (e.g. "
            "`from utils.roles.mapping import ROLE_FILE_META_SERVICES`) "
            "and use it everywhere the path is constructed, compared, or "
            "merged. Add `# nocheck: role-file-spot` (same-or-above) only "
            "for exceptions documented in "
            "docs/contributing/actions/testing/suppression.md."
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
