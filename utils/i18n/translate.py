"""Machine translation of the empty and fuzzy entries of a catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.i18n.catalog import (
    MACHINE_TRANSLATION,
    REFUSAL_PREFIX,
    TRANSLATION_REFUSED,
)
from utils.i18n.placeholders import harms

if TYPE_CHECKING:
    from babel.messages.catalog import Catalog, Message


def refusals(message: Message) -> list[str]:
    """Return the refusal annotations the entry carries.

    Matched by prefix, so a refusal another engine recorded still counts and
    is still cleared by ``retry``.

    Args:
        message: a catalog entry.
    """
    return [
        comment
        for comment in message.user_comments
        if comment.startswith(REFUSAL_PREFIX)
    ]


def refused(message: Message) -> bool:
    """Return whether a previous run recorded this entry as unanswerable.

    Args:
        message: a catalog entry.
    """
    return bool(refusals(message))


def pending(catalog: Catalog) -> list[Message]:
    """Return the entries of ``catalog`` that still need a translation.

    An entry the server already answered with a damaged span is skipped. The
    answer is deterministic for an unchanged source, so asking again spends a
    masking pass, a request and an inference to arrive at the same refusal.
    The mark rides in the entry's comments, so gettext drops it the moment the
    source changes and the entry is offered again by itself.

    Args:
        catalog: a language catalog.
    """
    return [
        message
        for message in catalog
        if isinstance(message.id, str)
        and message.id
        and (not message.string or message.fuzzy)
        and not refused(message)
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
    language = str(catalog.locale or "").split("_")[0]
    return [
        message
        for message in catalog
        if isinstance(message.id, str)
        and message.id
        and message.string
        and harms(message.id, str(message.string), language)
    ]


def discard(messages: list[Message]) -> None:
    """Empty the translation of every entry, so it becomes pending again.

    Args:
        messages: entries returned by ``damaged``.
    """
    for message in messages:
        message.string = ""
        message.flags.discard("fuzzy")


def retry(catalog: Catalog) -> int:
    """Drop the refusal mark from every entry carrying one.

    A refusal records what the server answered under the masking of the day.
    A source change clears it by itself, because the entry is then new; a
    change to the masking or to the damage predicate does not, and those
    entries would stay skipped forever.

    Args:
        catalog: a language catalog.

    Returns:
        How many entries were offered again.
    """
    cleared = 0
    for message in catalog:
        for stale in refusals(message):
            message.user_comments.remove(stale)
            cleared += 1
    return cleared


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
            if TRANSLATION_REFUSED not in message.user_comments:
                message.user_comments.append(TRANSLATION_REFUSED)
            continue
        message.string = text
        message.flags.discard("fuzzy")
        for stale in refusals(message):
            message.user_comments.remove(stale)
        if MACHINE_TRANSLATION not in message.user_comments:
            message.user_comments.append(MACHINE_TRANSLATION)
    return discarded
