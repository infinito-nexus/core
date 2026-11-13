"""Protection of the parts of a message that machine translation must not touch.

The public entry point of three layers, each importable on its own:

* :mod:`utils.i18n.spans`    which parts are protected, and how they are masked
* :mod:`utils.i18n.repairs`  the cosmetic repairs a restored string goes through
* :mod:`utils.i18n.damage`   whether what came back broke any of them
"""

from __future__ import annotations

import html

from utils.i18n.damage import Rejected as Rejected
from utils.i18n.damage import reason as reason
from utils.i18n.repairs import collapse as collapse
from utils.i18n.repairs import recapitalise as recapitalise
from utils.i18n.repairs import resegment as resegment
from utils.i18n.repairs import terminate as terminate
from utils.i18n.repairs import tighten as tighten
from utils.i18n.spans import TOKEN as TOKEN
from utils.i18n.spans import Masked as Masked


def unmask(
    translated: str, masked: Masked, source: str, language: str = ""
) -> str | Rejected:
    """Return the plain translation, or what was rejected and the criterion it broke.

    The rejected text travels with the verdict so the catalog can record it:
    a bare mark says an entry is unanswerable, the text says what the server
    answered, which is what an operator needs to judge the criterion.

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
            return Rejected(translated, "unknown-token")
        pieces.append(html.unescape(translated[position : match.start()]))
        pieces.append(masked.spans[index])
        seen.append(index)
        position = match.end()
    pieces.append(html.unescape(translated[position:]))
    restored = resegment(tighten("".join(pieces).strip()), masked.spans, source)
    restored = recapitalise(terminate(collapse(restored, source), source), source)
    if sorted(seen) != list(range(len(masked.spans))):
        return Rejected(restored, "lost-token")
    if not restored:
        return Rejected(translated, "empty")
    broke = reason(source, restored, language)
    return Rejected(restored, broke) if broke else restored
