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

from utils.i18n.placeholders import has_words, prose
from utils.meta.authors import author_names
from utils.meta.role.brands import brand_titles
from utils.software import SOFTWARE_NAME

URL = re.compile(r"^(?:https?://|www\.|mailto:|tel:)\S+$")


def _known() -> frozenset[str]:
    """Return every protected name, lower case."""
    names = (SOFTWARE_NAME, *brand_titles(), *author_names())
    return frozenset(name.lower() for name in names if name)


def is_name(text: str) -> bool:
    """Whether ``text`` is nothing but a brand, a credited person or a URL.

    The comparison runs against the prose, so the markdown a heading wraps the
    name in falls away first: ``**Mastodon**`` is the product under emphasis,
    not a phrase about it. Case is ignored because a page writes the name the
    way its sentence needs it, and ``**mailu**`` is still Mailu.

    An address is matched before that, on the raw text: masking protects the
    address of ``mailto:a@b.c`` but leaves the scheme behind, so its prose reads
    as a word.

    Args:
        text: a source message.
    """
    if URL.match(text.strip()):
        return True
    stripped = prose(text).strip()
    return bool(stripped) and stripped.lower() in _known()


def untranslatable(text: str) -> bool:
    """Whether ``text`` must stay in its source form.

    Args:
        text: a source message.
    """
    return not has_words(text) or is_name(text)
