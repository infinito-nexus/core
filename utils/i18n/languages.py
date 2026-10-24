"""The language list of ``meta/languages.yml``.

The file is the one place that names the languages this repository supports,
and it carries nothing but their identity: name, endonym and writing
direction. Every language it names gets a catalog in every domain.

Which engine renders into a language is deliberately not written here. The
translation gateway offers each backend that serves the pair, falls through to
the next one when an engine refuses or mangles the answer, drops an engine
whose failures pile up, and settles a language on the engine that wins its
comparisons. A static table beside that would be a second opinion that goes
stale the moment the router learns something. What a single engine can do is
declared with that engine instead: ``services.libretranslate-engine.serves``
of ``roles/svc-ai-libretranslate-engine`` states the codes its models cover,
because the lane prefetches those models before any engine can be asked.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

from utils.cache.yaml import load_yaml

SOURCE_LANGUAGE = "en"
LANGUAGES_FILE = Path("meta") / "languages.yml"
DOMAINS = ("core", "docs")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def load_languages(root: Path) -> dict[str, dict]:
    """Return every language of ``meta/languages.yml`` keyed by ISO 639-1 code.

    Args:
        root: repository root.
    """
    return load_yaml(root / LANGUAGES_FILE)


@lru_cache(maxsize=1)
def non_latin_languages(root: Path) -> frozenset[str]:
    """Return the codes whose endonym is not written in the Latin script.

    The endonym is the evidence: a language writes its own name in its own
    script, so the table already states which script each language expects
    and a second hand-kept list beside it only drifts. It drifted: the set
    this replaces named 41 languages and missed 21 the table answers for,
    Assamese among them, which is how a catalogue filled with Latin text
    passed every check.

    Args:
        root: repository root.
    """
    return frozenset(
        code
        for code, entry in load_languages(root).items()
        if _is_non_latin(str(entry.get("native", "")))
    )


@lru_cache(maxsize=1)
def language_scripts(root: Path) -> dict[str, str]:
    """Return the script each language writes its endonym in, keyed by ISO 639-1 code.

    Args:
        root: repository root.

    Returns:
        The :func:`script` most letters of the endonym belong to, for every
        language whose endonym carries a letter.
    """
    scripts = {}
    for code, entry in load_languages(root).items():
        tally = Counter(script(char) for char in str(entry["native"]) if char.isalpha())
        if tally:
            scripts[code] = tally.most_common(1)[0][0]
    return scripts


def script(char: str) -> str:
    """Return the script that opens the Unicode name of ``char``.

    Args:
        char: one character.

    Returns:
        The first word of its name, such as ``ARABIC`` or ``CJK``; empty when
        Unicode names no such character.
    """
    return unicodedata.name(char, "").replace("-", " ").partition(" ")[0]


def latin_share(text: str) -> float | None:
    """Return the share of this text's letters written in the Latin script.

    The script of a letter, not its codepoint range: ``ð`` and ``í`` are
    Latin and not ASCII, which is the difference between reading
    pseudo-Faroese as Latin text and reading it as something else.

    Args:
        text: any text; None when it carries no letter at all.
    """
    letters = [char for char in text if _LETTER.match(char)]
    if not letters:
        return None
    latin = sum(1 for char in letters if "LATIN" in unicodedata.name(char, ""))
    return latin / len(letters)


def _is_non_latin(endonym: str) -> bool:
    """Whether fewer than half of a name's letters are Latin ones."""
    share = latin_share(endonym)
    return share is not None and share < 0.5


def domain_languages(languages: dict[str, dict], domain: str) -> list[str]:
    """Return the codes that carry a catalog of ``domain``.

    Args:
        languages: the mapping returned by ``load_languages``.
        domain: a name of :data:`DOMAINS`.
    """
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain: {domain}")
    return sorted(code for code in languages if code != SOURCE_LANGUAGE)
