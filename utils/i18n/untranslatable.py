"""What a translator must never be handed, on either end of the pipeline.

Four shapes qualify. A message with no word at all is markup: ``[`e2e/`](e2e/)``
has nothing a translation could change. A message that is exactly a name is a
label: ``Mastodon`` is the product, ``Infinito.Nexus`` this software,
``Kevin Veen-Birkenbach`` the person, and a bare URL the address, and each must
read the same in every language.

A link whose label is its own target's filename is a path, not prose:
``[11_oidc.yml](../../group_vars/all/11_oidc.yml)`` would come back with a
translated filename. A label that says something about the target keeps its
translation, so ``[the OIDC defaults](../../group_vars/all/11_oidc.yml)`` is
still sent.

A message that is one technical token reads the same everywhere: an
abbreviation in capitals, a version, or a run of command-line options.

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
LINK = re.compile(r"^!?\[(?P<text>[^\]]*)\]\((?P<target>[^)]*)\)$")
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


def is_path_link(text: str) -> bool:
    """Whether ``text`` is a link that spells out the file it points at.

    ``[000.005.000-2025-12-30.md](docs/changelog/000.005.000-2025-12-30.md)``
    names its own target, so the label is a filename and not prose. It carries
    a word by the letters in its extension, which is why the markup rule lets
    it through and this one is needed.

    Args:
        text: a source message.
    """
    match = LINK.fullmatch(text.strip())
    if match is None:
        return False
    target = match["target"].split()[0] if match["target"].split() else ""
    return bool(target) and match["text"] == target.rstrip("/").rsplit("/", 1)[-1]


ABBREVIATION = re.compile(r"[A-Z][A-Z0-9_]{2,}")
VERSION = re.compile(r"v?\d+(?:\.\d+)+[\w.\-+]*|\d+\.x")
OPTION_RUN = re.compile(r"--[\w-]+(?:[= ]\S+)?(?:\s+--?[\w-]+(?:[= ]\S+)?)*")


def is_technical_token(text: str) -> bool:
    """Whether ``text`` is a token that reads the same in every language.

    Three shapes, each a whole message rather than a word inside one: an
    abbreviation written in capitals (``DKIM``, ``OIDC``, ``RBAC``), a version
    (``v2026.7.20``, ``18.x``), and a run of command-line options
    (``--distro debian --owner acme``). A translator asked for any of them
    answers with the same characters at best and a broken identifier at worst.

    Args:
        text: a source message.
    """
    stripped = text.strip()
    return any(
        pattern.fullmatch(stripped) for pattern in (ABBREVIATION, VERSION, OPTION_RUN)
    )


def untranslatable(text: str) -> bool:
    """Whether ``text`` must stay in its source form.

    Args:
        text: a source message.
    """
    return (
        not has_words(text)
        or is_name(text)
        or is_path_link(text)
        or is_technical_token(text)
    )
