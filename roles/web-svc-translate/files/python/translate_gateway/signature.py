"""Grouping requests so earlier verdicts apply to comparable ones.

A verdict is only worth reading back when the next request resembles the one
it was taken on. The signature states that resemblance in three terms the
request itself carries, so it can be computed without asking any engine.
"""

from __future__ import annotations

import hashlib
import re

LENGTH_BUCKETS = (64, 256, 1024, 4096)
MARKUP = re.compile(r"<[a-zA-Z/][^>]*>|&[a-z]+;|\{\{.*?\}\}|\[[^\]]+\]\([^)]+\)")


def length_class(text):
    """The bucket *text* falls into, as a string.

    A bucket rather than a length: two requests of 300 and 310 characters are
    the same kind of work, and keeping the exact length would give every
    request a signature of its own and a history of one row.
    """
    size = len(text or "")
    for limit in LENGTH_BUCKETS:
        if size <= limit:
            return f"<={limit}"
    return f">{LENGTH_BUCKETS[-1]}"


def carries_markup(text):
    """True when *text* holds tags, entities, placeholders or links.

    An engine that translates prose well can still mangle a placeholder, so
    markup separates the two populations rather than averaging them.
    """
    return bool(MARKUP.search(text or ""))


def signature(source, target, text):
    """The class this request belongs to, as one string."""
    shape = "markup" if carries_markup(text) else "plain"
    return f"{source or 'auto'}:{target}:{length_class(text)}:{shape}"


def cache_key(engine, source, target, text, fmt="text"):
    """What identifies a cached translation.

    The engine is part of the key: two engines answer the same request
    differently, and serving one's answer as the other's would make the
    learning log describe something that never happened. The format is part
    of it for the same reason: an engine asked in text mode translates a tag
    that the same engine in html mode leaves alone, so the two answers are
    not interchangeable.
    """
    digest = hashlib.sha256((text or "").encode()).hexdigest()
    return f"{engine}:{source or 'auto'}:{target}:{fmt}:{digest}"
