"""Machine translation of the empty and fuzzy entries of a catalog."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from utils.i18n.catalog import MACHINE_TRANSLATION
from utils.i18n.placeholders import protected_spans

if TYPE_CHECKING:
    from babel.messages.catalog import Catalog, Message

STRUCTURE = "[]{}`*()"


def structure(text: str) -> Counter:
    """Return the markup characters of ``text`` with their multiplicity.

    Args:
        text: a source message or its translation.
    """
    return Counter(character for character in text if character in STRUCTURE)


def pending(catalog: Catalog) -> list[Message]:
    """Return the entries of ``catalog`` that still need a translation.

    Args:
        catalog: a language catalog.
    """
    return [
        message
        for message in catalog
        if isinstance(message.id, str)
        and message.id
        and (not message.string or message.fuzzy)
    ]


def damaged(catalog: Catalog) -> list[Message]:
    """Return the entries whose translation altered a protected span or the markup around it.

    A tightened protection rule turns silently corrupted translations - a
    rewritten path, a dissolved markdown target - into entries this reports,
    so the next translation run redoes them. The markup comparison catches
    what masking cannot: a bracket the translator added or dropped next to a
    protected span leaves every span intact and still breaks the link.

    Args:
        catalog: a language catalog.
    """
    return [
        message
        for message in catalog
        if isinstance(message.id, str)
        and message.id
        and message.string
        and (
            protected_spans(str(message.string)) != protected_spans(message.id)
            or structure(str(message.string)) != structure(message.id)
        )
    ]


def discard(messages: list[Message]) -> None:
    """Empty the translation of every entry, so it becomes pending again.

    Args:
        messages: entries returned by ``damaged``.
    """
    for message in messages:
        message.string = ""
        message.flags.discard("fuzzy")


def apply(messages: list[Message], results: list[str | None]) -> int:
    """Store machine translations on ``messages``.

    Args:
        messages: entries returned by ``pending``.
        results: one translation per entry, ``None`` where it was discarded.

    Returns:
        The number of discarded translations; their entries stay unchanged.
    """
    discarded = 0
    for message, text in zip(messages, results, strict=True):
        if text is None:
            discarded += 1
            continue
        message.string = text
        message.flags.discard("fuzzy")
        if MACHINE_TRANSLATION not in message.user_comments:
            message.user_comments.append(MACHINE_TRANSLATION)
    return discarded
