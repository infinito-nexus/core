"""Cosmetic repairs a restored translation goes through.

Each one undoes a shape a translator produced and the source did not ask for.
They read the source only to decide whether something was lost, never to change
what the translation says.
"""

from __future__ import annotations

import re

from utils.i18n import names

EMPHASIS = re.compile(r"(\*\*)[ \t]*([^\s]|[^\s].*?[^\s])[ \t]*\1", re.DOTALL)
TERMINATORS = ".!?"
RUN_OF_SPACES = re.compile(r"[ \t]{2,}")


def resegment(restored: str, spans: tuple[str, ...], source: str) -> str:
    """Put back the sentence boundary a translator dropped behind a protected span.

    A name is skipped. Every other protected span ends in a delimiter, so a
    letter right behind it can only be the text the boundary was lost from, but
    a name ends in a word character and an agglutinative language suffixes it:
    ``Baserow`` is found inside the Bengali ``Baserowo`` and the punctuation
    would land inside the word.

    Args:
        restored: the translation with every protected span put back.
        spans: the protected spans of the source.
        source: the source message, which holds the boundary that went missing.
    """
    named = {source[start:end] for start, end in names.spans(source)}
    for span in spans:
        if span in named:
            continue
        start = source.find(span)
        if start < 0:
            continue
        boundary = source[start + len(span) : start + len(span) + 2]
        if len(boundary) != 2 or boundary[0] not in ".,;:" or not boundary[1].isspace():
            continue
        follows = restored.find(span) + len(span)
        if follows > len(span) - 1 and restored[follows : follows + 1].isalpha():
            restored = restored[:follows] + boundary[0] + " " + restored[follows:]
    return restored


def tighten(restored: str) -> str:
    """Return ``restored`` with the whitespace a translator set inside emphasis removed.

    Args:
        restored: the translation with every protected span put back.
    """
    return EMPHASIS.sub(
        lambda pair: pair.group(1) + pair.group(2) + pair.group(1), restored
    )


def collapse(restored: str, source: str) -> str:
    """Return ``restored`` without the space runs the translator opened.

    A run the source carries itself is left alone, because an aligned block in a
    code sample means its spacing.

    Args:
        restored: the translation with every protected span put back.
        source: the source message.
    """
    if "  " in source or "\t" in source:
        return restored
    return RUN_OF_SPACES.sub(" ", restored)


def terminate(restored: str, source: str) -> str:
    """Return ``restored`` with the sentence end the translator lost.

    A closing bracket that moves in front of a protected span takes the full
    stop behind it with it, which leaves the sentence running on.

    Args:
        restored: the translation with every protected span put back.
        source: the source message.
    """
    end = source.rstrip()[-1:]
    if end not in TERMINATORS or restored.rstrip().endswith(tuple(TERMINATORS)):
        return restored
    return restored.rstrip() + end


def recapitalise(restored: str, source: str) -> str:
    """Return ``restored`` with the capital its opening word lost.

    Args:
        restored: the translation with every protected span put back.
        source: the source message.
    """
    if not source[:1].isupper() or not restored[:1].islower():
        return restored
    return restored[0].upper() + restored[1:]
