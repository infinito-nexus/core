"""What a translator must never be handed, on either end of the pipeline.

Two shapes qualify. A message with no word at all is markup: ``[`e2e/`](e2e/)``
has nothing a translation could change. A message that is exactly a name is a
label: ``Mastodon`` is the product, ``Infinito.Nexus`` this software,
``Kevin Veen-Birkenbach`` the person, and a bare URL the address, and each must
read the same in every language.

Only a message that is nothing but the name qualifies. Inside a sentence the
name is protected by the span machinery in :mod:`utils.i18n.placeholders`, and
the sentence around it still needs translating.

The extraction and the translation client share this one function, so a message
the catalogs withhold is the same message the client would have refused to send.
"""

from __future__ import annotations

import re
import unicodedata

from utils.i18n.placeholders import has_words
from utils.meta.authors import author_names
from utils.meta.role.brands import brand_titles
from utils.software import SOFTWARE_NAME

URL = re.compile(r"^(?:https?://|www\.|mailto:|tel:)\S+$")
LINK = re.compile(r"^!?\[(?P<text>[^\]]*)\]\([^)]*\)$")
EMPHASIS = "*_`~ \t"
DECORATION = {"So", "Sk", "Cf", "Mn"}


def _bare(text: str) -> str:
    """Return ``text`` without the decoration a page wraps a name in.

    A heading writes the name with an emoji behind it and a table cell links it
    to the role that deploys it, so ``Git 🔐`` and ``[Baserow](roles/web-app-
    baserow/)`` are the product under decoration rather than a phrase about it.

    Only emphasis, a surrounding link and trailing symbols are removed. Taking
    the prose instead, as an earlier version did, drops every protected span:
    ``Redis ``cache``` then reads as ``Redis`` and 131 messages that say more
    than a name were withheld.

    Args:
        text: a source message.
    """
    bare = text.strip().strip(EMPHASIS)
    link = LINK.match(bare)
    if link:
        bare = link.group("text").strip().strip(EMPHASIS)
    while bare and unicodedata.category(bare[-1]) in DECORATION:
        bare = bare[:-1].strip(EMPHASIS)
    return bare


def _known() -> frozenset[str]:
    """Return every protected name, lower case."""
    names = (SOFTWARE_NAME, *brand_titles(), *author_names())
    return frozenset(name.lower() for name in names if name)


def is_name(text: str) -> bool:
    """Whether ``text`` is nothing but a brand, a credited person or a URL.

    The decoration a page wraps the name in is removed first; see :func:`_bare`.
    Case is ignored because a page writes the name the way its sentence needs
    it, and ``**mailu**`` is still Mailu.

    An address is matched before that, on the raw text, because a URL carries
    the characters the stripping removes.

    Args:
        text: a source message.
    """
    if URL.match(text.strip()):
        return True
    bare = _bare(text)
    return bool(bare) and bare.lower() in _known()


def untranslatable(text: str) -> bool:
    """Whether ``text`` must stay in its source form.

    Args:
        text: a source message.
    """
    return not has_words(text) or is_name(text)
