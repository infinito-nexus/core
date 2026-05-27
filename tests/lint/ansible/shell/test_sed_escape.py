# Integration test (unittest):
# Scan all Ansible task files under roles/*/tasks/**/*.yml and ensure that
# any sed substitution where the *replacement* part injects Jinja ({{ ... }})
# uses the `sed_escape` filter inside that replacement.
#
# Rationale:
# - sed replacement treats `&`, `\`, and the delimiter specially
# - secrets/passwords often contain these characters
#
# Notes:
# - Text-based scan (no YAML parsing) to handle Jinja + folded scalars robustly.
# - Enforces only when replacement contains `{{ ... }}`.
# - Ignores delimiter characters inside Jinja blocks {{ ... }} when parsing.
#
from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

TASK_FILES_GLOB = "roles/*/tasks/**/*.yml"


@dataclass(frozen=True)
class SedMatch:
    file: Path
    start: int
    end: int
    delimiter: str
    expr: str  # matched sed command snippet (best-effort)


def iter_task_files() -> Iterable[Path]:
    yield from sorted(PROJECT_ROOT.glob(TASK_FILES_GLOB))


def find_sed_substitutions(text: str, file: Path) -> list[SedMatch]:
    """
    Find sed substitution invocations like:
      sed -i "s|PAT|REPL|"
      sed -ri 's/..../..../'
    across possibly multi-line YAML scalars.

    Important:
    - When looking for the closing delimiters, delimiter characters inside Jinja
      blocks {{ ... }} are ignored so expressions like sed_escape('|') don't
      confuse the parser.
    """
    matches: list[SedMatch] = []

    # Broad match for a sed command that contains a substitution starting with s<delim>
    sed_cmd_re = re.compile(
        r"""
        sed                     # sed
        [^\S\r\n]+              # whitespace
        (?:-[^\n\r]+)*?         # flags like -i, -r, -E, etc. (best-effort, non-greedy)
        [^\S\r\n]+
        (?P<q>["'])?            # optional opening quote around expression
        s(?P<d>[^A-Za-z0-9\s])  # 's' + delimiter (non-alnum non-space)
        """,
        re.VERBOSE | re.MULTILINE,
    )

    for m in sed_cmd_re.finditer(text):
        d = m.group("d")
        q = m.group("q")

        # Find the third unescaped delimiter after "s<d>",
        # but ignore delimiter chars inside Jinja blocks {{ ... }}.
        i = m.end()
        delim_count = 0
        in_jinja = 0

        while i < len(text):
            if text.startswith("{{", i):
                in_jinja += 1
                i += 2
                continue
            if in_jinja > 0 and text.startswith("}}", i):
                in_jinja -= 1
                i += 2
                continue

            ch = text[i]

            if ch == "\\":
                i += 2
                continue

            if in_jinja == 0 and ch == d:
                delim_count += 1
                if delim_count == 3:
                    i += 1
                    break

            i += 1

        if delim_count < 3:
            continue

        end = i

        # Extend to closing quote if there was an opening quote
        if q:
            while end < len(text):
                ch = text[end]
                if ch == "\\":
                    end += 2
                    continue
                if ch == q:
                    end += 1
                    break
                end += 1

        snippet = text[m.start() : min(end, m.start() + 2000)]
        matches.append(
            SedMatch(file=file, start=m.start(), end=end, delimiter=d, expr=snippet)
        )

    return matches


def extract_replacement(expr: str) -> tuple[str, str] | None:
    """
    Given a sed snippet that includes `s<d>`, extract (delimiter, replacement_part).
    Ignores delimiter characters inside Jinja blocks {{ ... }}.
    """
    m = re.search(r"s(?P<d>[^A-Za-z0-9\s])", expr)
    if not m:
        return None
    d = m.group("d")

    # Parse: s<d> PAT <d> REPL <d> ...
    rest = expr[m.end() :]
    parts: list[str] = []
    buf: list[str] = []

    i = 0
    in_jinja = 0

    while i < len(rest):
        # Enter/exit Jinja blocks
        if rest.startswith("{{", i):
            in_jinja += 1
            buf.append("{{")
            i += 2
            continue
        if in_jinja > 0 and rest.startswith("}}", i):
            in_jinja -= 1
            buf.append("}}")
            i += 2
            continue

        ch = rest[i]

        # Preserve escaped characters
        if ch == "\\" and i + 1 < len(rest):
            buf.append(ch)
            buf.append(rest[i + 1])
            i += 2
            continue

        # Only treat delimiter as delimiter when NOT inside Jinja
        if in_jinja == 0 and ch == d:
            parts.append("".join(buf))
            buf = []
            if len(parts) == 3:
                break
            i += 1
            continue

        buf.append(ch)
        i += 1

    if len(parts) < 2:
        return None

    replacement = parts[1]
    return d, replacement


class TestSedEscapeUsage(unittest.TestCase):
    def test_all_sed_replacements_use_sed_escape_filter_for_jinja_in_replacement(
        self,
    ) -> None:
        violations: list[str] = []

        for file in iter_task_files():
            try:
                text = read_text(str(file))
            except UnicodeDecodeError:
                continue
            sed_matches = find_sed_substitutions(text, file)

            for sm in sed_matches:
                extracted = extract_replacement(sm.expr)
                if not extracted:
                    continue

                d, replacement = extracted

                # Only enforce when replacement injects Jinja
                if "{{" not in replacement:
                    continue

                # Enforce sed_escape is used in the replacement segment (not just anywhere)
                if "sed_escape" not in replacement:
                    ctx_start = max(0, sm.start - 200)
                    ctx_end = min(len(text), sm.end + 200)
                    context = text[ctx_start:ctx_end].strip()

                    violations.append(
                        "\n".join(
                            [
                                f"{file}: sed replacement injects Jinja but does not use sed_escape",
                                f"  Detected delimiter: {d!r}",
                                "  Context:",
                                context,
                            ]
                        )
                    )

        if violations:
            self.fail("\n\n".join(violations))


if __name__ == "__main__":
    unittest.main()
