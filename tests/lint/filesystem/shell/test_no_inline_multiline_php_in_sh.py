"""Forbid multi-line inline PHP code embedded in ``*.sh`` files.

When a shell script needs to drive PHP (most commonly via
``compose exec ... php -r '...'`` or a ``php <<EOF`` heredoc), the PHP
body MUST live in a sibling ``files/<name>.php`` file. The shell script
should pipe that file through stdin to the ``php`` interpreter, e.g.

    ${BIN_COMPOSE} exec -T -i \\
      -e "FOO=${FOO}" --user "${USER}" "${SERVICE}" \\
      php < "$(dirname "$0")/<name>.php"

Or — preferred from Ansible — drop the wrapper ``.sh`` entirely and use
``ansible.builtin.shell`` with ``stdin: "{{ lookup('file', '<name>.php') }}"``.

Why
---
* Embedding multi-line PHP inside a shell scalar couples three escaping
  layers (bash, the surrounding YAML / template, and PHP) into a single
  string — the brittle interaction is what produced the
  Jinja-into-PHP-single-quote injection risk in the original
  ``set_siteurl.sh`` body.
* ``.php`` files round-trip cleanly through editors, language servers
  and PHP linters and stay reviewable in isolation from the
  orchestration glue.
* Variables that need to cross the boundary should be passed via
  ``compose exec -e VAR=...`` and read with ``getenv()`` inside PHP —
  this also avoids escaping problems with values that contain quotes.

What this lint flags
--------------------
Two opening shapes inside a ``.sh`` scanned under ``roles/``,
``scripts/`` or ``.github/``:

  1. ``php -r <quote>`` where the matching closing ``<quote>`` is on a
     LATER physical line. A single-line ``php -r 'echo "hi";'`` is
     fine.
  2. ``php`` followed (anywhere on the line) by a ``<<EOF`` heredoc
     redirection whose terminator marker is on a LATER line. ``-`` /
     quoting variants (``<<-EOF``, ``<<'EOF'``, ``<<"EOF"``) are all
     covered.

A run that spans more than one physical line is reported. The shorter
``php -r 'one-liner'`` form is judged to fit safely as an inline call.
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

# Top-level path segments where shell files are scanned. Tests/, docs/
# and similar are exempt.
SCAN_DIRS = ("roles", "scripts", ".github")
SCAN_SUFFIXES = (".sh", ".bash")

# php -r '   or   php -r "    (capturing the opening quote).
_PHP_R_OPEN_RE = re.compile(r"""\bphp\s+-r\s+(?P<q>['"])""")

# php  ...  <<['"]?MARK['"]?  (also <<-, allowing leading dash).
# Captures the heredoc end-marker. Anything between `php` and `<<` is
# tolerated to allow `php -dfoo=1 <<EOF` and similar.
_PHP_HEREDOC_OPEN_RE = re.compile(
    r"""\bphp\b[^<\n]*<<-?\s*(?P<mq>['"]?)(?P<mark>[A-Za-z_][A-Za-z0-9_]*)(?P=mq)"""
)


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    kind: str  # "php -r" or "php <<HEREDOC"
    span_lines: int

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        suggested = rel.rsplit("/", 1)[0] + "/" + Path(rel).stem + ".php"
        return (
            f"{rel}:{self.line}: inline {self.kind} body spans "
            f"{self.span_lines} lines — extract to "
            f"{suggested.replace('files/', 'files/').rsplit('/', 2)[0]}/files/<name>.php "
            "and pipe it via stdin (e.g. "
            "`${BIN_COMPOSE} exec -T -i ... php < <name>.php`) or, "
            "from Ansible, use `shell:` with "
            "`stdin: \"{{ lookup('file', '<name>.php') }}\"`."
        )


def _iter_shell_files(repo_root: Path) -> Iterable[Path]:
    """Yield ``.sh`` / ``.bash`` files under any of SCAN_DIRS via the
    shared project-walk cache.
    """
    scan_set = set(SCAN_DIRS)
    repo_str = str(repo_root)
    for path_str in iter_project_files(extensions=SCAN_SUFFIXES):
        rel_first = (
            Path(path_str).relative_to(repo_str).parts[0]
            if Path(path_str).is_absolute()
            else path_str.split("/", 1)[0]
        )
        if rel_first in scan_set:
            yield Path(path_str)


def _find_php_r_close(
    lines: list[str], start_idx: int, quote: str, after_col: int
) -> int | None:
    """Return the index of the line that closes a ``php -r <quote>``
    block opened on ``lines[start_idx]`` at ``after_col``. The closing
    rule is the first occurrence of *quote* that is not preceded by an
    odd number of backslashes. Returns None if unterminated.
    """
    first = lines[start_idx][after_col:]
    if _has_unescaped(first, quote):
        return start_idx
    for i in range(start_idx + 1, len(lines)):
        if _has_unescaped(lines[i], quote):
            return i
    return None


def _has_unescaped(segment: str, quote: str) -> bool:
    """Return True if *segment* contains *quote* not preceded by an odd
    number of backslashes. Bash single-quoted strings cannot be escaped
    at all (a literal ``'`` must close the string), but we treat the
    rule uniformly — a stray escaped quote inside a double-quoted body
    is still unlikely to terminate.
    """
    i = 0
    while i < len(segment):
        c = segment[i]
        if c == quote:
            backslashes = 0
            j = i - 1
            while j >= 0 and segment[j] == "\\":
                backslashes += 1
                j -= 1
            if backslashes % 2 == 0:
                return True
        i += 1
    return False


def _find_heredoc_close(lines: list[str], start_idx: int, marker: str) -> int | None:
    """Return the index of the line that terminates a heredoc opened on
    ``lines[start_idx]`` with end-marker ``marker``. The terminator is
    the first subsequent line whose stripped content equals *marker*.
    Note: ``<<-MARK`` allows leading tabs on the terminator; we accept
    leading whitespace generally, which is a small over-acceptance but
    safe for a lint.
    """
    for i in range(start_idx + 1, len(lines)):
        if lines[i].strip() == marker:
            return i
    return None


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        m = _PHP_R_OPEN_RE.search(line)
        if m:
            quote = m.group("q")
            after_col = m.end()
            close_idx = _find_php_r_close(lines, i, quote, after_col)
            if close_idx is not None and close_idx > i:
                findings.append(
                    Finding(
                        file=path,
                        line=i + 1,
                        kind=f"php -r {quote}…{quote}",
                        span_lines=close_idx - i + 1,
                    )
                )
                i = close_idx + 1
                continue

        m = _PHP_HEREDOC_OPEN_RE.search(line)
        if m:
            marker = m.group("mark")
            close_idx = _find_heredoc_close(lines, i, marker)
            if close_idx is not None and close_idx > i + 1:
                findings.append(
                    Finding(
                        file=path,
                        line=i + 1,
                        kind=f"php <<{marker}",
                        span_lines=close_idx - i + 1,
                    )
                )
                i = close_idx + 1
                continue

        i += 1

    return findings


class TestNoInlineMultilinePhpInSh(unittest.TestCase):
    def test_no_multiline_php_bodies_in_shell_scripts(self) -> None:
        """``php -r '<body>'`` and ``php <<EOF`` blocks inside ``*.sh``
        / ``*.bash`` files MUST NOT span more than one physical line.
        Anything longer should live in a sibling ``files/<name>.php``
        and be piped via stdin (or loaded from Ansible via
        ``lookup('file', ...)``)."""
        findings: list[Finding] = []
        for sh_file in _iter_shell_files(PROJECT_ROOT):
            findings.extend(_scan_file(sh_file))

        if findings:
            formatted = "\n".join(f.format(PROJECT_ROOT) for f in findings)
            self.fail(
                f"{len(findings)} multi-line inline PHP block(s) in "
                f"shell scripts:\n" + formatted
            )


if __name__ == "__main__":
    unittest.main()
