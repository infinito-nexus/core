"""Forbid selector lists that mix a vendor-prefixed pseudo with other selectors.

A browser drops a whole rule when one selector of its list is invalid, and
every engine treats the other engines' prefixed pseudos (``::-moz-selection``,
``:-ms-input-placeholder``, ``::-webkit-input-placeholder``) as invalid. A list
such as ``.CodeMirror-selected, ::-moz-selection { ... }`` therefore never
applies in Chromium. Each vendor-prefixed pseudo needs its own rule, which is
what ``gen_css.py`` emits since it keys merged rules by that pseudo.

Scans role stylesheets: ``*.css`` and ``*.css.j2`` under ``roles/``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_VENDOR_PSEUDO = re.compile(r"::?-(?:webkit|moz|ms|o)-[\w-]+")
_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_PRELUDE = re.compile(r"([^{};]+)\{")


def _mask(text: str) -> str:
    """Replace Jinja tags and CSS comments with spaces of the same length.

    Args:
        text: Stylesheet source.

    Returns:
        The text with every Jinja tag and comment blanked, offsets unchanged.
    """
    for pattern in (_JINJA, _COMMENT):
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _split_selectors(prelude: str) -> list[str]:
    """Split a selector list at top-level commas.

    Args:
        prelude: The text before a rule's ``{``.

    Returns:
        The stripped selectors, commas inside parentheses kept.
    """
    parts, depth, start = [], 0, 0
    for index, char in enumerate(prelude):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(prelude[start:index])
            start = index + 1
    parts.append(prelude[start:])
    return [part.strip() for part in parts if part.strip()]


def mixed_vendor_lists(text: str) -> list[tuple[int, str]]:
    """Find selector lists that mix vendor pseudo keys.

    Args:
        text: Stylesheet source, Jinja allowed.

    Returns:
        ``(offset, prelude)`` for every rule whose selectors carry more than
        one distinct vendor-pseudo key, where no vendor pseudo is its own key.
    """
    found = []
    for match in _PRELUDE.finditer(_mask(text)):
        prelude = match.group(1)
        if prelude.strip().startswith("@"):
            continue
        keys = {
            tuple(sorted(set(_VENDOR_PSEUDO.findall(selector))))
            for selector in _split_selectors(prelude)
        }
        if len(keys) > 1:
            offset = match.start(1) + len(prelude) - len(prelude.lstrip())
            found.append((offset, prelude.strip()))
    return found


class TestCssVendorPseudoLists(unittest.TestCase):
    def test_no_mixed_vendor_pseudo_selector_lists(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(extensions=(".css", ".css.j2")):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith("roles/"):
                continue
            text = read_text(path_str)
            for offset, prelude in mixed_vendor_lists(text):
                lineno = text.count("\n", 0, offset) + 1
                offenders.append(f"{rel}:{lineno}: {prelude[:120]}")

        if offenders:
            self.fail(
                f"{len(offenders)} selector list(s) mix a vendor-prefixed pseudo "
                "with other selectors, so browsers drop the whole rule. Give "
                "each vendor-prefixed pseudo its own rule.\n" + "\n".join(offenders)
            )

    def test_detects_a_mixed_list_and_accepts_split_rules(self) -> None:
        mixed = ".a, ::-moz-selection { color: red; }"
        split = ".a { color: red; }\n::-moz-selection { color: red; }"
        same_vendor = "a::-moz-selection, b::-moz-selection { color: {{ c }}; }"
        self.assertEqual(len(mixed_vendor_lists(mixed)), 1)
        self.assertEqual(mixed_vendor_lists(split), [])
        self.assertEqual(mixed_vendor_lists(same_vendor), [])
        self.assertEqual(mixed_vendor_lists(":is(.a, ::-moz-x) { x: y; }"), [])


if __name__ == "__main__":
    unittest.main()
