"""Lint guard for `.env`-format files across the whole repo.

Scope: every committed ``*.env`` and ``*.env.j2`` file, plus the
generated repo-root ``.env`` if present. ``.env.j2`` files are treated
as Jinja templates -- ``{% ... %}`` blocks and ``{# ... #}`` comments
are recognised but not validated as env-file syntax.

Rules (apply to every line that resolves to a KEY/value pair):

1. Each line is either blank, a full-line ``# ...`` comment, a
   Jinja control/comment (only in ``.env.j2``), or a ``KEY=value``
   entry. Nothing else.
2. ``KEY=value`` lines have NO whitespace around ``=``
   (``KEY = value`` and ``KEY= value`` are rejected).
3. The key matches ``^[A-Za-z_][A-Za-z0-9_]*$``.
4. Inline comments after ``=`` are forbidden (``KEY=value # comment``);
   put the comment ABOVE the key.
5. The comment block directly above a ``KEY=value`` line (no blank
   line between them) MUST be single-line. Multi-line comment blocks
   are allowed only as file headers / section dividers (separated
   from the next key by a blank line).
6. In ``env/*.env`` and the generated ``.env``, that block MUST
   carry exactly one *non-nocheck* comment line (i.e. every key
   has its own one-line doc). In ``*.env.j2`` templates the
   *non-nocheck* line MAY be zero or one.
7. ``# nocheck: ...`` suppress markers do NOT count toward the
   per-key-comment budget -- you can stack as many as you need.
   This is the only way multi-line comment blocks above a key are
   allowed; everything else is rejected.
8. Non-nocheck comment lines MUST be no longer than 140 characters
   (including the leading ``# ``). Forces the comment to focus on
   the core message; if you need more context, move it to the file
   header above a blank line. ``# nocheck: ...`` markers are exempt
   from the length cap (they often carry justification text).

Style guidance for the one comment line (see `docs/contributing/documentation.md`):

- Explain *why* something is unusual, not *what* obvious code does.
- English, current-state phrasing only -- no history (``previously``,
  ``replaces X``, ``after the refactor`` etc.).
- No em dashes (``--`` or ``—``) as clause separators; prefer plain
  sentences with regular punctuation.
- No requirement-file references (see documentation.md for the rule).
"""

from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENTRY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
_JINJA_STMT_RE = re.compile(r"^\s*\{%.*%\}\s*$")
_JINJA_COMMENT_RE = re.compile(r"^\s*\{#.*#\}\s*$")
_NOCHECK_RE = re.compile(r"^#\s*nocheck\b")
_MAX_COMMENT_LEN = 140


def _is_nocheck_comment(raw: str) -> bool:
    return bool(_NOCHECK_RE.match(raw.lstrip()))


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int
    rule: str
    detail: str


def _has_inline_comment(value: str) -> bool:
    """Return True if `value` contains an unquoted `#` after the `=`."""
    in_single = False
    in_double = False
    for ch in value:
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if ch == "#" and not in_single and not in_double:
            return True
    return False


def validate_env_file(path: Path, *, strict: bool) -> list[Violation]:
    """Validate one env file.

    ``strict=True`` requires exactly one per-key comment line. False
    allows zero or one (multi-line still rejected)."""
    violations: list[Violation] = []
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    is_jinja = path.suffix == ".j2"
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError) as exc:
        return [Violation(rel, 0, "read-error", str(exc))]
    lines = text.splitlines()
    pending: list[
        tuple[int, str]
    ] = []  # consecutive `#`-comment lines since last reset
    in_jinja_comment = False  # for multi-line `{# ... #}` blocks

    for idx, raw in enumerate(lines, 1):
        stripped = raw.strip()

        # Continue / close a multi-line Jinja comment.
        if in_jinja_comment:
            pending = []
            if "#}" in raw:
                in_jinja_comment = False
            continue

        if not stripped:
            pending = []
            continue

        # Jinja constructs in templates: reset pending and skip the line.
        if is_jinja:
            if _JINJA_STMT_RE.match(raw) or _JINJA_COMMENT_RE.match(raw):
                pending = []
                continue
            # Multi-line Jinja comment opener.
            if stripped.startswith("{#") and "#}" not in stripped:
                pending = []
                in_jinja_comment = True
                continue

        if stripped.startswith("#"):
            if raw.lstrip() != raw:
                violations.append(
                    Violation(
                        rel,
                        idx,
                        "leading-whitespace",
                        f"comment line must start at column 0 (got {raw!r})",
                    )
                )
            if not _is_nocheck_comment(raw) and len(raw) > _MAX_COMMENT_LEN:
                violations.append(
                    Violation(
                        rel,
                        idx,
                        "comment-too-long",
                        f"non-nocheck comment line is {len(raw)} chars "
                        f"(max {_MAX_COMMENT_LEN}); focus on the core message",
                    )
                )
            pending.append((idx, raw))
            continue

        # Must be a KEY=value line.
        if "=" not in raw:
            violations.append(
                Violation(
                    rel,
                    idx,
                    "syntax",
                    f"line is neither blank, comment, nor KEY=value: {raw!r}",
                )
            )
            pending = []
            continue

        key_part, _, value_part = raw.partition("=")
        match = _ENTRY_RE.match(raw)

        if match is None:
            if key_part != key_part.rstrip() or value_part != value_part.lstrip():
                violations.append(
                    Violation(
                        rel,
                        idx,
                        "no-space-around-equals",
                        f"whitespace around `=` is forbidden: {raw!r}",
                    )
                )
            if not _KEY_RE.match(key_part.strip()):
                violations.append(
                    Violation(
                        rel,
                        idx,
                        "invalid-key",
                        f"key must match [A-Za-z_][A-Za-z0-9_]*: {key_part.strip()!r}",
                    )
                )
            pending = []
            continue

        key = match.group("key")
        value = match.group("value")

        if raw != f"{key}={value}":
            violations.append(
                Violation(
                    rel,
                    idx,
                    "non-canonical-line",
                    f"expected exact `{key}={value}` (got {raw!r})",
                )
            )

        if _has_inline_comment(value):
            violations.append(
                Violation(
                    rel,
                    idx,
                    "no-inline-comment",
                    "inline `#` comment after `=` is forbidden; move it above the key",
                )
            )

        # Per-key comment shape (nocheck markers exempt from the count):
        # * strict (env/*.env + generated .env): exactly 1 non-nocheck line.
        # * soft (.env.j2 templates): 0 or 1 non-nocheck line.
        non_nocheck = sum(1 for _, line in pending if not _is_nocheck_comment(line))
        if strict:
            if non_nocheck != 1:
                violations.append(
                    Violation(
                        rel,
                        idx,
                        "per-key-comment-required",
                        f"strict env-file: expected exactly 1 non-nocheck comment "
                        f"line above {key}=... (got {non_nocheck}); "
                        "nocheck markers don't count toward the budget",
                    )
                )
        elif non_nocheck > 1:
            violations.append(
                Violation(
                    rel,
                    idx,
                    "per-key-comment-multi-line",
                    f"per-key comment block has {non_nocheck} non-nocheck `#`-lines "
                    f"above {key}=...; only one is allowed (nocheck markers may stack)",
                )
            )

        pending = []

    return violations


def _git_ls_files() -> list[str]:
    # `safe.directory=*` bypasses git's ownership check, which fails
    # inside the dev container when the bind-mounted repo's UID does
    # not match the container user.
    out = subprocess.check_output(
        [
            "git",
            "-c",
            "safe.directory=*",
            "-C",
            str(PROJECT_ROOT),
            "ls-files",
        ],
        text=True,
    )
    return [line for line in out.splitlines() if line]


def _scan_targets() -> list[tuple[Path, bool]]:
    """Return (path, strict) pairs for every env-file the lint covers."""
    targets: list[tuple[Path, bool]] = []
    for rel in _git_ls_files():
        if rel.endswith(".env"):
            strict = rel.startswith("env/") or rel == ".env"
            targets.append((PROJECT_ROOT / rel, strict))
        elif rel.endswith(".env.j2"):
            targets.append((PROJECT_ROOT / rel, False))
    # Include the generated `.env` even though it is gitignored.
    root_env = PROJECT_ROOT / ".env"
    if root_env.is_file() and not any(p == root_env for p, _ in targets):
        targets.append((root_env, True))
    return targets


class TestEnvFileSchema(unittest.TestCase):
    def test_env_files_conform_to_schema(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no env files found to validate")
        all_violations: list[Violation] = []
        for path, strict in targets:
            all_violations.extend(validate_env_file(path, strict=strict))
        if all_violations:
            grouped: dict[str, list[Violation]] = {}
            for v in all_violations:
                grouped.setdefault(v.file, []).append(v)
            lines = [
                f"env-file schema violations "
                f"({len(all_violations)} across {len(grouped)} file(s)):"
            ]
            for f, vs in sorted(grouped.items()):
                lines.append(f"  {f}:")
                lines.extend(f"    line {v.line_no} [{v.rule}]: {v.detail}" for v in vs)
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
