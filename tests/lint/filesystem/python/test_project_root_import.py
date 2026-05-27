"""Lint that pins ``PROJECT_ROOT`` to a single canonical source.

Three rules are enforced:

1. Every Python file in the repo (``*.py``) MUST NOT compute the
   project root locally. The forbidden patterns are:

   * a top-level assignment that climbs ``parents[N]`` from
     ``__file__`` into a ``*_ROOT``-style variable,
   * a bare ``Path(__file__).…parents`` chain (no ``[N]`` index)
     used to iterate upward in search of the root,
   * any chain of ``..`` segments (string literals or ``os.pardir``
     references) used to walk up to the root,
   * a function such as ``repo_root()`` / ``project_root()`` (or
     their underscore-prefixed ``_repo_root`` / ``_project_root``
     siblings) that searches upward for ``pyproject.toml``.

   The single legitimate definition site is the package's own
   ``__init__.py``. Consumers MUST import ``PROJECT_ROOT`` from there
   (relatively as ``from . import PROJECT_ROOT`` or absolutely as
   ``from <pkg> import PROJECT_ROOT``) so a future move of the file
   does not silently break a hard-coded ``parents[N]`` index.

2. ``PROJECT_ROOT`` itself MUST only be assigned inside an
   ``__init__.py``. A ``PROJECT_ROOT = …`` line anywhere else (test
   modules, ``__main__.py`` shims, helper modules, …) fails the lint
   even when the right-hand side does not climb ``parents[N]`` —
   re-binding the constant locally defeats the single-source guarantee
   rule 1 was added to enforce.

3. Every ``__init__.py`` that DOES define ``PROJECT_ROOT`` MUST point
   at a directory containing ``pyproject.toml``. A wrong
   ``parents[N]`` index turns the constant into a silent footgun;
   the lint catches it the moment the index drifts off the repo root.

Suppression
-----------

Bootstrap files that prepend the repo root to ``sys.path`` before any
package import resolves (the ``__main__`` shims under ``cli/``) MUST
mark the offending line with ``# nocheck: project-root-import`` and
explain why the local computation is unavoidable. The same applies to
standalone scripts under ``roles/<role>/files/`` that have no
package container to import from. See
[suppression.md](../../../docs/contributing/actions/testing/suppression.md).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_non_ignored_files, read_text

SUPPRESS_RULE: str = "project-root-import"


# Regexes for forbidden patterns that compute a path relative to the
# repo root. Every match is reported individually so the failure
# message can name the specific shape that fired.
#
# The catalog is intentionally broad: ANY `parents[N]` index expression
# and ANY ".." segment in a path-construction context flags. Files that
# legitimately need to walk to the repo root (sys.path bootstrap shims,
# standalone scripts without a package container) MUST mark the line
# with `# nocheck: project-root-import` and document why.
_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "`parents[N]` index expression",
        re.compile(r"\.parents\[\s*\d+\s*\]"),
        "stripped",
    ),
    (
        # Catches the chained ``.parent.parent.…`` upward walk, the
        # attribute-access twin of ``parents[N]``. Functionally
        # identical, so subject to the same ban: any walk of two or
        # more ``.parent`` accesses chained directly on
        # ``Path(__file__)`` MUST use ``parents[N]`` (with the same
        # ``__init__.py``-only rule) or import ``PROJECT_ROOT`` from
        # the package. The match is anchored at ``Path(__file__)`` so
        # walks on a derived path object (e.g. ``services_file.parent
        # .parent.name`` to extract a role name from a known
        # ``meta/services.yml`` path) do not flag.
        "chained `Path(__file__)…parent.parent.…` upward walk",
        re.compile(
            r"Path\(\s*__file__\s*\)(?:\s*\.\s*[A-Za-z_]\w*\([^)]*\))*"
            r"(?:\s*\.\s*parent\b){2,}"
        ),
        "stripped",
    ),
    (
        # Catches the bare ``Path(__file__).resolve().parents`` chain
        # (no ``[N]`` index) used in ``for candidate in
        # Path(__file__).resolve().parents`` upward-search loops.
        # The indexed ``parents[N]`` form is already covered above; the
        # un-indexed form is the iterator hand-roll that the
        # ``def repo_root()`` helpers below typically wrap.
        "`Path(__file__).…parents` upward iteration",
        re.compile(
            r"Path\(\s*__file__\s*\)(?:\s*\.\s*[A-Za-z_]\w*\([^)]*\))*"
            r"\s*\.\s*parents\b(?!\s*\[)"
        ),
        "stripped",
    ),
    (
        "`os.pardir` reference",
        re.compile(r"\bos\.pardir\b"),
        "stripped",
    ),
    # Catches ``".."``, ``"../.."``, ``"../../../"`` (any number of
    # ``..`` segments separated by ``/``, with optional trailing
    # ``/``). Runs against the *no-docs* view of the source so a
    # docstring or ``# comment`` mentioning ``..`` does NOT trip it,
    # while a real ``Path(... / ".." / ...)`` callsite does.
    (
        # nocheck: project-root-import  catalog entry mentions the literal pattern by design
        '".." path segment in a path-construction context',
        re.compile(r"""["']\.\.(?:/+\.\.)*/?["']"""),
        "no_docs",
    ),
    (
        # Underscore-prefixed variants (``_repo_root`` / ``_project_root``)
        # are caught alongside the public names — the leading underscore
        # only marks the helper as private, the upward-walk it performs
        # is the same drift this lint is built to forbid.
        "function searching upward for pyproject.toml",
        re.compile(r"^\s*def\s+_*(?:repo_root|project_root)\s*\("),
        "stripped",
    ),
)

# A top-level ``PROJECT_ROOT`` (or ``PROJECT_ROOT: <type>``) assignment.
# Allowed only inside ``__init__.py``; everywhere else the constant
# MUST be imported via ``from . import PROJECT_ROOT`` (or
# ``from <pkg> import PROJECT_ROOT``).
#
# The regex anchors at the start of a (stripped) line so neither
# ``_PROJECT_ROOT`` (a private re-binding) nor a regex source string
# mentioning ``PROJECT_ROOT`` triggers it. The negative ``(?!=)``
# lookahead after ``=`` keeps a bare comparison (``PROJECT_ROOT == …``)
# from matching.
_PROJECT_ROOT_ASSIGN_RE = re.compile(r"^\s*PROJECT_ROOT(?:\s*:\s*[^=]+?)?\s*=(?!=)")

# The legitimate `PROJECT_ROOT = …` definition shape inside an
# ``__init__.py``. The integrity check (does the resolved path carry
# `pyproject.toml`?) only fires when this exact shape is seen, so a
# package that re-exports the constant via ``from . import PROJECT_ROOT``
# does not accidentally count as a definition.
_INIT_PROJECT_ROOT_RE = re.compile(
    r"^\s*PROJECT_ROOT(?:\s*:\s*[A-Za-z_][\w\[\], ]*)?\s*=\s*"
    r"Path\(\s*__file__\s*\)\s*\.resolve\(\)\.parents\[\s*(\d+)\s*\]"
)


def _is_init_file(path: Path) -> bool:
    return path.name == "__init__.py"


def _strip_strings_and_comments(text: str) -> str:
    """Return *text* with every string literal and `#` comment replaced
    by whitespace that preserves line numbers and column offsets.

    The forbidden patterns must only fire on real code, never on
    documentation that mentions the patterns by name (the catalog
    rule definitions in this very file, the dictionary docstring of
    `utils/cache/__init__.py`, etc.).
    """
    return _strip(text, keep_inline_strings=False)


def _strip_docs_and_comments(text: str) -> str:
    """Like :func:`_strip_strings_and_comments`, but preserve regular
    single-line ``"…"`` and ``'…'`` literals.

    Used by the ``".."`` rule, which deliberately scans the *content*
    of path strings: with the inline strings stripped (the default
    behaviour above) the regex would never match a real
    ``Path(… / ".." / …)`` callsite, while a docstring or
    ``# comment`` mentioning ``..`` should still be ignored.
    """
    return _strip(text, keep_inline_strings=True)


def _strip(text: str, *, keep_inline_strings: bool) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if text[i : i + 3] in ('"""', "'''"):
            quote = text[i : i + 3]
            end = text.find(quote, i + 3)
            if end == -1:
                out.append("\n" * text[i:].count("\n"))
                break
            block = text[i : end + 3]
            out.append("".join("\n" if c == "\n" else " " for c in block))
            i = end + 3
            continue
        if ch in ('"', "'"):
            quote = ch
            j = i + 1
            while j < n and text[j] != quote:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if text[j] == "\n":
                    break
                j += 1
            block = text[i : j + 1]
            if keep_inline_strings:
                out.append(block)
            else:
                out.append("".join("\n" if c == "\n" else " " for c in block))
            i = j + 1
            continue
        if ch == "#":
            j = text.find("\n", i)
            if j == -1:
                out.append(" " * (n - i))
                break
            out.append(" " * (j - i))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _scan_file(path: Path) -> list[str]:
    """Return human-readable failure descriptions for *path*.

    Empty list means the file is clean. Suppression markers are
    consulted on the offending line and the line directly above
    (`same-or-above` semantics matching the rest of the suppression
    catalog).
    """
    try:
        text = read_text(str(path))
    except Exception:
        return []

    raw_lines = text.splitlines()
    code_lines = _strip_strings_and_comments(text).splitlines()
    no_docs_lines = _strip_docs_and_comments(text).splitlines()
    failures: list[str] = []

    is_init = _is_init_file(path)

    for lineno in range(1, len(raw_lines) + 1):
        stripped = code_lines[lineno - 1] if lineno - 1 < len(code_lines) else ""
        no_docs = no_docs_lines[lineno - 1] if lineno - 1 < len(no_docs_lines) else ""
        for label, pattern, scan_mode in _FORBIDDEN_PATTERNS:
            target = stripped if scan_mode == "stripped" else no_docs
            if not pattern.search(target):
                continue
            # Inside __init__.py the canonical PROJECT_ROOT definition
            # is allowed; the per-init `pyproject.toml` integrity check
            # below validates that one. Other forbidden shapes
            # (pardir chains, def repo_root) MUST still fail even in
            # __init__.py, because there is no reason to use them there.
            if is_init and _INIT_PROJECT_ROOT_RE.match(stripped):
                continue
            if is_suppressed_at(raw_lines, lineno, SUPPRESS_RULE, mode="same-or-above"):
                continue
            failures.append(f"{path}:{lineno}: {label}")

        # `PROJECT_ROOT = …` is allowed only inside an ``__init__.py``.
        # Anywhere else the constant MUST be imported from the package.
        if (
            not is_init
            and _PROJECT_ROOT_ASSIGN_RE.match(stripped)
            and not is_suppressed_at(
                raw_lines, lineno, SUPPRESS_RULE, mode="same-or-above"
            )
        ):
            failures.append(
                f"{path}:{lineno}: `PROJECT_ROOT` assignment outside "
                f"`__init__.py` (import via `from . import PROJECT_ROOT` "
                f"or `from <pkg> import PROJECT_ROOT` instead)"
            )

    return failures


def _check_init_project_root(path: Path) -> list[str]:
    """If *path* is an ``__init__.py`` that defines ``PROJECT_ROOT`` at
    top level via ``Path(__file__).resolve().parents[N]``, validate
    that the resolved path actually carries ``pyproject.toml``."""
    if not _is_init_file(path):
        return []
    try:
        text = read_text(str(path))
    except Exception:
        return []

    failures: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _INIT_PROJECT_ROOT_RE.match(line)
        if not m:
            continue
        depth = int(m.group(1))
        try:
            resolved = path.resolve().parents[depth]
        except IndexError:
            failures.append(
                f"{path}:{lineno}: PROJECT_ROOT parents[{depth}] is out of "
                f"range for this file's depth."
            )
            continue
        if not (resolved / "pyproject.toml").is_file():
            failures.append(
                f"{path}:{lineno}: PROJECT_ROOT resolves to {resolved}, "
                f"which does not contain pyproject.toml; fix the "
                f"parents[{depth}] index."
            )
    return failures


class TestProjectRootImport(unittest.TestCase):
    def test_no_local_project_root_computation(self):
        # Walk only non-gitignored files so vendored skill packages under
        # `.agents/` and `.claude/skills/` (which carry their own
        # `parents[N]` boilerplate by upstream design) do NOT count.
        offenders: list[str] = []
        for path_str in iter_non_ignored_files(extensions=(".py",)):
            path = Path(path_str)
            offenders.extend(_scan_file(path))
            offenders.extend(_check_init_project_root(path))

        if offenders:
            self.fail(
                f"{len(offenders)} project-root violation(s):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
