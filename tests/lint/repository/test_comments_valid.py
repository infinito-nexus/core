"""Lint: source files may carry only *useful* comments, so code stays readable.

A comment is VALID only when it is one of:

* a **file-header** block (leading comment lines explaining the file),
* a **doc comment** directly above a class / function / method / rule,
* a **tool directive** (`noqa`, `nocheck`, `type: ignore`, `shellcheck`,
  `rubocop:`, `stylelint-disable`, `pragma`, language annotations, ...),
* a **marked exception** -- a mid-code comment that flags a real trip-wire
  (warning, pitfall, deliberate non-idiomatic choice) whose text starts with
  one of the exception markers (`Exception`, ...).

Mid-code comments are ONLY allowed as exceptions. Plain narration, banners,
restating the next line, or neutral `Note:`-style info carry no warning and so
get flagged for deletion -- headers and doc comments above defs are the place
for explanation, the code body is only interrupted for genuine exceptions.

Checks ``.py .sh .yml/.yaml .rb .php .css`` plus ``.j2`` templates: the ``.j2``
suffix is stripped so the underlying language's comments are linted (``foo.yml.j2``
-> ``.yml`` rules, ``foo.php.j2`` -> ``.php`` rules, anything else -> ``#``), and
Jinja ``{# #}`` comments are checked on top. Python is parsed with ``tokenize``
(string-aware, exact). Python additionally flags bare string-expression
statements (``\"\"\"...\"\"\"`` / ``'''...'''`` / plain literals) outside
docstring position: a string floating in a body is a comment in disguise and
runs through the same validity rules. Docstrings (first statement of a
module/class/function) and PEP 224 attribute docstrings (string directly
after an assignment) stay untouched. The line-based languages flag full-line
``#`` comments plus ``/* */`` blocks; trailing inline comments are
intentionally OUT of scope (reliably distinguishing them from ``#`` inside a
string needs a full lexer per language, and false positives would make the
linter unusable).

SCOPE: only files that are staged, unstaged, or untracked against ``HEAD`` are
checked. The legacy tree is grandfathered in -- it never breaks the build --
while every file a change touches must satisfy the policy going forward.

A whole file opts out with a ``# nocheck: comments-valid`` marker in its first
30 lines (any comment prefix, e.g. ``{# nocheck: comments-valid #}`` for Jinja),
for vendored/upstream config templates whose inline docs are all intentional.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_FILE_NOCHECK_RULE = "comments-valid"

_MARKERS = (
    "todo",
    "fixme",
    "hack",
    "xxx",
    "warn",
    "attention",
    "danger",
    "exception",
    "sec",
    "safety",
    "deprecated",
    "limitation",
)
_MARKER_RE = re.compile(rf"^[\s*/#>-]*(?:{'|'.join(_MARKERS)})\b", re.IGNORECASE)

_DIRECTIVE_RE = re.compile(
    r"\b("
    r"noqa|nocheck|nosec|bandit|type:\s*ignore|type:\s*\w|pragma|pylint|mypy|ruff"
    r"|flake8|pyright|isort|fmt:\s*(?:on|off)|yapf|coding[:=]|shellcheck|yamllint"
    r"|hadolint"
    r"|rubocop|frozen_string_literal|sourcery|phpcs|phpstan|psalm|phan"
    r"|codingStandardsIgnore|stylelint|eslint|prettier|jscpd|checkov|tflint"
    r"|ansible-lint|markdownlint|shfmt|depend(?:abot|s)|renovate"
    r")\b",
    re.IGNORECASE,
)

_DEF_RE = {
    ".py": re.compile(r"^\s*(?:@|(?:async\s+)?def\s|class\s)"),
    ".rb": re.compile(r"^\s*(?:def\s|class\s|module\s|[A-Z_]+\s*=|attr_)"),
    ".sh": re.compile(r"^\s*(?:function\s+[\w-]+|[\w-]+\s*\(\)\s*\{?)"),
    ".php": re.compile(
        r"^\s*(?:(?:final|abstract|public|private|protected|static|readonly|\s)*"
        r"function\s|(?:final|abstract\s)*class\s|interface\s|trait\s|enum\s|namespace\s)"
    ),
    ".css": re.compile(r"^\s*[.#:@a-zA-Z\[&*].*\{\s*$"),
}

_HEADER_SKIP = re.compile(r"^\s*(?:#!|<\?php|---|\.\.\.|/\*|\*|\*/|//|#|\{#)")
_PROLOGUE = re.compile(
    r"^\s*(?:set |set\b|shopt|IFS=|export |readonly |umask |source |\. /|use strict"
    r"|use \w|package |from __future__ |require |require_relative )"
)


def _py_comments(text: str):
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return [
        (t.start[0], t.string.lstrip("#").strip())
        for t in toks
        if t.type == tokenize.COMMENT
    ]


def _py_stray_strings(text: str):
    """Bare string-expression statements outside docstring position.

    A triple-quoted (or plain) string literal floating in a body is a
    comment in disguise and is validated like any other comment. Allowed
    positions: first statement of a module/class/function (docstring) and
    directly after an assignment (PEP 224 attribute docstring).
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    def _is_str_expr(stmt) -> bool:
        return (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )

    allowed: set[int] = set()
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if not isinstance(body, list):
                continue
            for idx, stmt in enumerate(body):
                if not _is_str_expr(stmt):
                    continue
                is_docstring = (
                    field == "body"
                    and idx == 0
                    and isinstance(
                        node,
                        (
                            ast.Module,
                            ast.ClassDef,
                            ast.FunctionDef,
                            ast.AsyncFunctionDef,
                        ),
                    )
                )
                after_assign = (
                    field == "body"
                    and idx > 0
                    and isinstance(node, (ast.Module, ast.ClassDef))
                    and isinstance(body[idx - 1], (ast.Assign, ast.AnnAssign))
                )
                if is_docstring or after_assign:
                    allowed.add(id(stmt))

    out = []
    for node in ast.walk(tree):
        if _is_str_expr(node) and id(node) not in allowed:
            first = " ".join(node.value.value.strip().split())
            end = node.end_lineno or node.lineno
            out.append((node.lineno, first, set(range(node.lineno, end + 1))))
    return out


def _hash_comments(lines):
    out = []
    for i, line in enumerate(lines, 1):
        s = line.lstrip()
        if s.startswith("#") and not s.startswith("#!"):
            out.append((i, s[1:].strip(), {i}))
    return out


def _php_comments(lines):
    out = []
    in_block = False
    block_start = 0
    block_lines: set[int] = set()
    block_body: list[str] = []
    for i, line in enumerate(lines, 1):
        if in_block:
            block_lines.add(i)
            end = line.find("*/")
            block_body.append(line if end < 0 else line[:end])
            if end >= 0:
                out.append(
                    (block_start, " ".join(block_body).strip(" *"), set(block_lines))
                )
                in_block = False
            continue
        s = line.lstrip()
        start = line.find("/*")
        if start >= 0 and "*/" not in line[start:]:
            in_block = True
            block_start = i
            block_lines = {i}
            block_body = [line[start + 2 :]]
            continue
        if start >= 0:
            end = line.find("*/", start)
            out.append((i, line[start + 2 : end].strip(), {i}))
            continue
        if s.startswith("//"):
            out.append((i, s[2:].strip(), {i}))
        elif s.startswith("#") and not s.startswith("#["):
            out.append((i, s[1:].strip(), {i}))
    return out


def _css_comments(lines):
    out = []
    in_block = False
    block_start = 0
    block_lines: set[int] = set()
    block_body: list[str] = []
    for i, line in enumerate(lines, 1):
        cursor = 0
        while True:
            if in_block:
                block_lines.add(i)
                end = line.find("*/", cursor)
                if end < 0:
                    block_body.append(line[cursor:])
                    break
                block_body.append(line[cursor:end])
                out.append(
                    (block_start, " ".join(block_body).strip(" *"), set(block_lines))
                )
                in_block = False
                cursor = end + 2
                continue
            start = line.find("/*", cursor)
            if start < 0:
                break
            in_block = True
            block_start = i
            block_lines = {i}
            block_body = [line[start + 2 :]]
            cursor = len(line)
            break
    return out


def _jinja_comments(lines):
    out = []
    in_block = False
    block_start = 0
    block_lines: set[int] = set()
    block_body: list[str] = []
    for i, line in enumerate(lines, 1):
        cursor = 0
        while True:
            if in_block:
                block_lines.add(i)
                end = line.find("#}", cursor)
                if end < 0:
                    block_body.append(line[cursor:])
                    break
                block_body.append(line[cursor:end])
                out.append(
                    (block_start, " ".join(block_body).strip(" #"), set(block_lines))
                )
                in_block = False
                cursor = end + 2
                continue
            start = line.find("{#", cursor)
            if start < 0:
                break
            end = line.find("#}", start + 2)
            if end < 0:
                in_block = True
                block_start = i
                block_lines = {i}
                block_body = [line[start + 2 :]]
                break
            out.append((i, line[start + 2 : end].strip(" #"), {i}))
            cursor = end + 2
    return out


def _header_end(lines) -> int:
    end = 0
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s or _HEADER_SKIP.match(line) or _PROLOGUE.match(line):
            end = i
            continue
        break
    return end


def _next_code_is_def(start_lineno, lines, comment_lines, ext) -> bool:
    pat = _DEF_RE.get(ext)
    if pat is None:
        return False
    for idx in range(start_lineno, len(lines)):
        n = idx + 1
        if n in comment_lines:
            continue
        if not lines[idx].strip():
            continue
        return bool(pat.match(lines[idx]))
    return False


def _is_full_line(lineno, lines) -> bool:
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1].lstrip().startswith(("#", "//", "/*", "*", "{#"))
    return False


def _blocks(comments, lines):
    """Group consecutive FULL-LINE comments into blocks; trailing comments are
    singletons. A multi-line warning keeps its marker on the first line only, so
    the whole contiguous block inherits the first line's validity."""
    blocks: list[list] = []
    for lineno, body, span in comments:
        start, end = min(span), max(span)
        full = _is_full_line(start, lines)
        if full and blocks and blocks[-1][-1][3] and start == blocks[-1][-1][2] + 1:
            blocks[-1].append((lineno, body, end, full))
        else:
            blocks.append([(lineno, body, end, full)])
    return blocks


def find_invalid_comments(path: Path):
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    if is_suppressed_in_head(lines, _FILE_NOCHECK_RULE):
        return []
    ext = path.suffix
    underlying = path.with_suffix("").suffix if ext == ".j2" else ext

    if underlying == ".py":
        py = _py_comments(text)
        if py is None:
            return []
        comments = sorted(
            [(ln, body, {ln}) for ln, body in py] + _py_stray_strings(text),
            key=lambda c: c[0],
        )
    elif underlying in (".yml", ".yaml", ".sh", ".rb") or path.name == "Dockerfile":
        comments = _hash_comments(lines)
    elif underlying == ".php":
        comments = _php_comments(lines)
    elif underlying == ".css":
        comments = _css_comments(lines)
    elif ext == ".j2":
        comments = _hash_comments(lines)
    else:
        return []

    if ext == ".j2":
        comments = sorted(comments + _jinja_comments(lines), key=lambda c: c[0])

    header_end = _header_end(lines)
    comment_lines = {ln for c in comments for ln in c[2]}
    invalid = []
    for block in _blocks(comments, lines):
        first_body = block[0][1]
        block_marker = bool(_MARKER_RE.match(first_body))
        block_def = _next_code_is_def(block[-1][2], lines, comment_lines, underlying)
        for lineno, body, _end, _full in block:
            if not body:
                continue
            if _DIRECTIVE_RE.search(body) or block_marker:
                continue
            if lineno <= header_end or block_def:
                continue
            invalid.append((lineno, body))
    return invalid


_EXTS = (".py", ".sh", ".yml", ".yaml", ".rb", ".php", ".css", ".j2")


def _git_lines(args: list[str]) -> list[str]:
    """Run a git command and return its stdout lines.

    safe.directory='*' is required because the make-test container mounts the
    repo as a different uid; bare git would abort with dubious-ownership and the
    linter would silently scan zero files.
    """
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory=*", *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return result.stdout.splitlines()


def _changed_targets():
    """Files staged, unstaged, or untracked vs HEAD -- the working-tree diff.

    The linter checks only what a change touches, so the legacy tree never
    breaks the build while every file in a new change must comply.
    """
    rel = set(_git_lines(["diff", "--name-only", "HEAD"]))
    rel |= set(_git_lines(["ls-files", "--others", "--exclude-standard"]))
    targets = []
    for r in sorted(rel):
        if r.endswith(_EXTS) or r.rsplit("/", 1)[-1] == "Dockerfile":
            path = PROJECT_ROOT / r
            if path.is_file():
                targets.append(path)
    return targets


class TestCommentsValid(unittest.TestCase):
    def test_only_valid_comments(self) -> None:
        offenders = []
        for path in _changed_targets():
            for lineno, body in find_invalid_comments(path):
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}: {body[:70]}")
        if offenders:
            shown = "\n".join(sorted(offenders)[:200])
            self.fail(
                f"{len(offenders)} invalid comment(s). A comment is allowed only as a "
                "file header, a doc comment directly above a class/function/rule, a "
                "tool directive (noqa/nocheck/...), or a mid-code EXCEPTION that flags "
                "a real trip-wire (starts with Exception/...). Everything else is narration: DELETE it "
                "(move real explanation into the file header or a doc comment):\n"
                + shown
            )


if __name__ == "__main__":
    unittest.main()
