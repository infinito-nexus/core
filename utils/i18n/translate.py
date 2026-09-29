"""Machine translation of the empty and fuzzy entries of a catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.i18n.catalog import (
    ENGINE,
    MACHINE_TRANSLATION,
    REFUSAL_PREFIX,
    REJECTED_PREFIX,
    TRANSLATION_REFUSED,
)
from utils.i18n.placeholders import (
    COLLAPSE_FLOOR,
    MAX_SHARING_SOURCES,
    Rejected,
    harms,
    protected_spans,
)
from utils.i18n.spans import prose

if TYPE_CHECKING:
    from collections import Counter

    from babel.messages.catalog import Catalog, Message

REFUSAL_PREFIXES = (REFUSAL_PREFIX, REJECTED_PREFIX)
URL_SUPPRESSION = "nocheck: url"
DUPLICATE = "duplicate"


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
        if comment.startswith(REFUSAL_PREFIXES)
    ]


def clear(message: Message) -> int:
    """Drop the annotations a previous rejection wrote on ``message``.

    The suppression is dropped only where it introduces a quote of this
    module's making. Sphinx carries a source comment into the catalog as a
    user comment, so a ``nocheck`` standing anywhere else belongs to the
    message and removing it would let the URL probe loose on the ``msgid``.

    Args:
        message: a catalog entry.

    Returns:
        How many annotations were dropped.
    """
    comments = message.user_comments
    keep = []
    for index, comment in enumerate(comments):
        after = comments[index + 1] if index + 1 < len(comments) else ""
        introduces = comment == URL_SUPPRESSION and after.startswith(REJECTED_PREFIX)
        if not comment.startswith(REFUSAL_PREFIXES) and not introduces:
            keep.append(comment)
    dropped = len(comments) - len(keep)
    message.user_comments = keep
    return dropped


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


def over_shared(catalog: Catalog) -> list[Message]:
    """Return the entries too many distinct sources translate the same way.

    :func:`damaged` reads one entry at a time and cannot see this: each entry
    is individually sound, and what is gone is the distinction between them.
    :func:`apply` turns a repeat down through ``taken``, so a catalog reaches
    this state only when two runs translated it at once, each holding its own
    view of what was already spent. Every sharer is cleared rather than all
    but one: the run that produced them gave no reason to believe any one of
    them belongs to the source it landed on.

    Args:
        catalog: a language catalog.
    """
    sharers: dict[str, list[Message]] = {}
    for message in catalog:
        if not message.id or not message.string:
            continue
        if MACHINE_TRANSLATION not in (message.user_comments or []):
            continue
        if not _own_translation_due(str(message.id)):
            continue
        sharers.setdefault(str(message.string), []).append(message)
    return [
        message
        for shared in sharers.values()
        if len(shared) > MAX_SHARING_SOURCES
        for message in shared
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
    return sum(1 for message in catalog if refused(message) and clear(message))


SPAN_CRITERION = "protected-span"
DETAIL_SPANS = 6


def _detail(message: Message, rejected: Rejected) -> str:
    """Return the spans that made a rejection, for the marker to carry.

    Args:
        message: the entry being annotated.
        rejected: what came back and why it was turned down.
    """
    if rejected.reason != SPAN_CRITERION or not isinstance(message.id, str):
        return ""
    source = protected_spans(message.id)
    answer = protected_spans(rejected.text)
    lost = sorted(source - answer)[:DETAIL_SPANS]
    gained = sorted(answer - source)[:DETAIL_SPANS]
    return f" lost={lost} gained={gained}".replace("\n", "\\n")


def record(message: Message, rejected: Rejected | None) -> None:
    """Annotate ``message`` as unanswerable, quoting what was turned down.

    The rejected text is a comment and never a ``msgstr``: it is what the
    consumers must not use, while an operator judging the criterion needs to
    read it. A newline is escaped because a ``.po`` comment ends at one. The
    ``nocheck`` goes on a line of its own above the quote, never behind it: a
    mangled link is exactly what a rejection quotes and the URL probe reads
    comments too, while a long quote is wrapped over several comment lines,
    which would carry the marker away from the URL it has to cover.

    Args:
        message: a catalog entry.
        rejected: what came back and why it was turned down, ``None`` when the
            server never answered at all.
    """
    clear(message)
    if rejected is None:
        message.user_comments.append(TRANSLATION_REFUSED)
        return
    message.user_comments.append(
        f"{REFUSAL_PREFIX} {ENGINE} {rejected.reason}{_detail(message, rejected)}"
    )
    message.user_comments.append(URL_SUPPRESSION)
    message.user_comments.append(
        f"{REJECTED_PREFIX} {rejected.text}".replace("\n", "\\n").rstrip("\\")
    )


def _own_translation_due(source: str) -> bool:
    """Return whether ``source`` is long enough to deserve its own translation.

    Short entries legitimately share one: several buttons are all ``Save``.
    The floor is the one the collapse check reads, and inclusive as it is
    there, so the writer turns down exactly what the release gate reports
    rather than leaving it a source of exactly that length.

    Args:
        source: the source message.
    """
    return len(prose(source).strip()) >= COLLAPSE_FLOOR


def taken_translations(catalog: Catalog) -> set[str]:
    """Return the translations ``catalog`` already spends on a long source.

    Args:
        catalog: the catalog about to be translated into.
    """
    return {
        str(message.string)
        for message in catalog
        if message.id and message.string and _own_translation_due(str(message.id))
    }


def apply(
    messages: list[Message],
    results: list[str | Rejected | None],
    taken: set[str] | None = None,
    criteria: Counter[str] | None = None,
) -> int:
    """Store machine translations on ``messages``.

    Args:
        messages: entries returned by ``pending``.
        results: one entry per message: the translation, a ``Rejected``, or
            ``None`` where the server never answered.
        criteria: tally the caller prints, which counts what the client
            rejected. A duplicate is turned down here rather than there, so
            without this the run reports the discard and no reason for it.
        taken: translations this catalog already carries for a source long
            enough to deserve its own. A repeat is turned down: what is wrong
            with it is not its shape, which every predicate passes, but that
            another entry already says it. Pass None to skip the check, which
            is what a caller without the whole catalog must do.

    Returns:
        The number of discarded translations; their entries keep no ``msgstr``.
    """
    discarded = 0
    for message, text in zip(messages, results, strict=True):
        if not isinstance(text, str):
            discarded += 1
            record(message, text)
            continue
        if taken is not None and _own_translation_due(str(message.id)):
            if text in taken:
                discarded += 1
                record(message, Rejected(text, DUPLICATE))
                if criteria is not None:
                    criteria[DUPLICATE] += 1
                continue
            taken.add(text)
        message.string = text
        message.flags.discard("fuzzy")
        clear(message)
        if MACHINE_TRANSLATION not in message.user_comments:
            message.user_comments.append(MACHINE_TRANSLATION)
    return discarded
