"""Protection of the parts of a message that machine translation must not touch.

The public entry point of three layers, each importable on its own:

* :mod:`utils.i18n.spans`    which parts are protected, and how they are masked
* :mod:`utils.i18n.repairs`  the cosmetic repairs a restored string goes through
* :mod:`utils.i18n.damage`   whether what came back broke any of them
"""

from __future__ import annotations

import html

from utils.i18n.damage import ECHO_FLOOR as ECHO_FLOOR
from utils.i18n.damage import LATIN_FLOOR as LATIN_FLOOR
from utils.i18n.damage import LATIN_SHARE as LATIN_SHARE
from utils.i18n.damage import MARKUP as MARKUP
from utils.i18n.damage import NON_LATIN_SCRIPTS as NON_LATIN_SCRIPTS
from utils.i18n.damage import STRUCTURE as STRUCTURE
from utils.i18n.damage import STUTTER as STUTTER
from utils.i18n.damage import TRUNCATION_FLOOR as TRUNCATION_FLOOR
from utils.i18n.damage import TRUNCATION_RATIO as TRUNCATION_RATIO
from utils.i18n.damage import WORDS as WORDS
from utils.i18n.damage import harms as harms
from utils.i18n.damage import missing_names as missing_names
from utils.i18n.damage import protected_spans as protected_spans
from utils.i18n.damage import structure as structure
from utils.i18n.damage import stutters as stutters
from utils.i18n.damage import truncated as truncated
from utils.i18n.damage import untranslated as untranslated
from utils.i18n.repairs import EMPHASIS as EMPHASIS
from utils.i18n.repairs import RUN_OF_SPACES as RUN_OF_SPACES
from utils.i18n.repairs import TERMINATORS as TERMINATORS
from utils.i18n.repairs import collapse as collapse
from utils.i18n.repairs import recapitalise as recapitalise
from utils.i18n.repairs import resegment as resegment
from utils.i18n.repairs import terminate as terminate
from utils.i18n.repairs import tighten as tighten
from utils.i18n.spans import EXTRA as EXTRA
from utils.i18n.spans import PLACEHOLDER as PLACEHOLDER
from utils.i18n.spans import PRINTF as PRINTF
from utils.i18n.spans import PROTECTED as PROTECTED
from utils.i18n.spans import TOKEN as TOKEN
from utils.i18n.spans import Masked as Masked
from utils.i18n.spans import carries_placeholder as carries_placeholder
from utils.i18n.spans import has_words as has_words
from utils.i18n.spans import mask as mask
from utils.i18n.spans import matches as matches
from utils.i18n.spans import prose as prose


def unmask(
    translated: str, masked: Masked, source: str, language: str = ""
) -> str | None:
    """Return the plain translation, or ``None`` when it damaged a protected span.

    Args:
        translated: the HTML the translator returned for ``masked``.
        masked: the request built by ``mask``.
        source: the source message.
        language: ISO 639-1 code of the catalog being filled.
    """
    seen: list[int] = []
    pieces: list[str] = []
    position = 0
    for match in TOKEN.finditer(translated):
        index = int(match.group(1))
        if index >= len(masked.spans):
            return None
        pieces.append(html.unescape(translated[position : match.start()]))
        pieces.append(masked.spans[index])
        seen.append(index)
        position = match.end()
    pieces.append(html.unescape(translated[position:]))
    restored = resegment(tighten("".join(pieces).strip()), masked.spans, source)
    restored = recapitalise(terminate(collapse(restored, source), source), source)
    if sorted(seen) != list(range(len(masked.spans))):
        return None
    if not restored or harms(source, restored, language):
        return None
    return restored
