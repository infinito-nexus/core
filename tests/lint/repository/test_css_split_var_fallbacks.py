"""Forbid ``var()`` fallbacks whose color was pushed out of the parentheses.

Mapping a literal color inside a ``var()`` fallback to a token once wrote the
token after the closing parenthesis: ``var(--tw-shadow, 0 0 #0000)`` became
``var(--tw-shadow, 0 0 ) transparent``. As soon as the outer variable is set,
the value carries two colors, the declaration is invalid at computed-value time
and the property falls back to its initial value, so the shadow or border
silently disappears. The signature is a fallback that ends in whitespace right
before its closing parenthesis; a deliberate empty fallback is written
``var(--x,)``.

Scans role stylesheets: ``*.css``, ``*.css.j2`` and ``*.scss`` under ``roles/``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_SPLIT_FALLBACK = re.compile(r"var\(--[\w-]+,[^()]*\s\)")


def split_fallbacks(text: str) -> list[tuple[int, str]]:
    """Find ``var()`` calls whose fallback ends in whitespace.

    Args:
        text: Stylesheet source, Jinja allowed.

    Returns:
        ``(offset, match)`` for every such ``var()`` call.
    """
    return [(match.start(), match.group(0)) for match in _SPLIT_FALLBACK.finditer(text)]


class TestCssSplitVarFallbacks(unittest.TestCase):
    def test_no_var_fallback_split_from_its_color(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(extensions=(".css", ".css.j2", ".scss")):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith("roles/"):
                continue
            text = read_text(path_str)
            for offset, found in split_fallbacks(text):
                lineno = text.count("\n", 0, offset) + 1
                offenders.append(f"{rel}:{lineno}: {found}")

        if offenders:
            self.fail(
                f"{len(offenders)} var() fallback(s) end in whitespace, so the "
                "color that belongs inside the fallback stands after it and the "
                "declaration turns invalid once the variable is set. Move the "
                "color into the fallback.\n" + "\n".join(offenders)
            )

    def test_detects_split_fallbacks_and_accepts_whole_ones(self) -> None:
        self.assertEqual(
            len(split_fallbacks("box-shadow: var(--a, 0 0 ) transparent;")), 1
        )
        self.assertEqual(len(split_fallbacks("--b: var(--c, ) var(--design-link);")), 1)
        self.assertEqual(split_fallbacks("box-shadow: var(--a, 0 0 transparent);"), [])
        self.assertEqual(split_fallbacks("--b: var(--c,var(--design-link));"), [])
        self.assertEqual(split_fallbacks("--b: var(--c,) var(--d);"), [])
        self.assertEqual(
            split_fallbacks("color: var(--c, rgba(var(--d-rgb), 0.3));"), []
        )


if __name__ == "__main__":
    unittest.main()
