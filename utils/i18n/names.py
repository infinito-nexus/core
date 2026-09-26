"""The role names and product titles a translation must hand back unchanged.

A role directory name is never an English phrase, so it is protected wherever it
appears. A title is a single word often enough that the two readings collide:
``Unbound`` is a DNS resolver and an adjective, ``Shell`` a role and a common
noun. Measured over the catalogs, the capital separates them: of 47932
capitalised occurrences the translator altered 22 percent, among them
``(Unbound, etc.)`` turning into ``(Ungebunden, etc.)``, while the 40698
lowercase ones it altered in 40 percent of cases and those readings were the
common noun the text meant (``shell extensions``, ``user-driven documentation``).
"""

from __future__ import annotations

import re
from functools import lru_cache

from utils.cache.files import PROJECT_ROOT
from utils.meta.role.names import role_names
from utils.meta.role.titles import role_titles

SENTENCE_END = re.compile(r"[.!?:;\n]\s*[*_`\"'(\[]*\s*$")
OPENERS = " *_`\"'(["


def _alternation(names) -> str:
    """Return a regex matching any of ``names``, longest first.

    The boundaries end at a word character, not at a hyphen: German compounds a
    name with the noun it qualifies, so ``Redis-Benutzer`` and ``API-URL`` carry
    the name intact and must not read as a loss. Matching the longest name first
    keeps ``web-app-keycloak`` from being served by a shorter sibling.

    Args:
        names: the literals to match.
    """
    ordered = sorted(names, key=len, reverse=True)
    return r"(?<!\w)(?:" + "|".join(re.escape(n) for n in ordered) + r")(?!\w)"


@lru_cache(maxsize=1)
def patterns(
    root: str = str(PROJECT_ROOT),
) -> tuple[re.Pattern | None, re.Pattern | None]:
    """Return the unconditional and the capitalisation-gated name patterns.

    Args:
        root: repository root.

    Returns:
        The pattern for hyphenated role names, which hold wherever they appear,
        and the one for titles, which holds only on a capitalised occurrence.
    """
    roles, titles = role_names(root), role_titles(root)
    hyphenated = [name for name in roles if "-" in name]
    return (
        re.compile(_alternation(hyphenated)) if hyphenated else None,
        re.compile(_alternation(titles)) if titles else None,
    )


def reads_as_a_name(text: str, start: int) -> bool:
    """Return whether the title at ``start`` is a product name, not a noun.

    The capital carries the distinction only away from a sentence start, where
    every word is capitalised anyway: ``(Unbound, etc.)`` names a DNS resolver,
    while the heading ``Documentation`` is the common noun the translator is
    meant to render.

    Args:
        text: the message the occurrence sits in.
        start: offset of the occurrence.
    """
    if not text[start].isupper():
        return False
    before = text[:start].rstrip(OPENERS)
    return bool(before) and not SENTENCE_END.search(before)


def spans(text: str) -> list[tuple[int, int]]:
    """Return the offsets of every name ``text`` carries.

    Args:
        text: a source message.
    """
    role_pattern, title_pattern = patterns()
    found = []
    if role_pattern:
        found += [(m.start(), m.end()) for m in role_pattern.finditer(text)]
    if title_pattern:
        found += [
            (m.start(), m.end())
            for m in title_pattern.finditer(text)
            if reads_as_a_name(text, m.start())
        ]
    return found
