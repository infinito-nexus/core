"""Build the knowledge index of one deployment.

Every document of every staged source is cut into passages at its headings,
each passage is masked by :func:`assistant.scrub.scrub`, embedded, and the
whole set replaces the previous index in one store call, so a question never
meets a half-built index.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from assistant.scrub import leaks, scrub

_HEADING = re.compile(r"^(?=#{1,6}\s)", re.MULTILINE)


@dataclass(frozen=True)
class Passage:
    """One indexed piece of a document.

    Args:
        source: the name of the source the document belongs to.
        title: the document title.
        url: the public URL of the document.
        text: the masked passage text.
        score: the similarity to a question; 0 while the passage is stored.
    """

    source: str
    title: str
    url: str
    text: str
    score: float = 0.0


def passages(document, size: int) -> list[Passage]:
    """Cut a document into masked passages of at most *size* characters.

    Args:
        document: an :class:`assistant.sources.Document`.
        size: the longest passage in characters.
    """
    pieces: list[str] = []
    for section in _HEADING.split(document.text):
        rest = section.strip()
        while len(rest) > size:
            cut = rest.rfind("\n", 0, size)
            cut = cut if cut > 0 else size
            pieces.append(rest[:cut].strip())
            rest = rest[cut:].strip()
        if rest:
            pieces.append(rest)
    return [
        Passage(document.source, document.title, document.url, scrub(piece))
        for piece in pieces
        if piece
    ]


async def build(documents, embedder, store, size: int) -> int:
    """Replace the index in *store* with the passages of *documents*.

    Args:
        documents: the :class:`assistant.sources.Document` list to index.
        embedder: offers ``embed(texts) -> list[list[float]]``.
        store: offers the coroutine ``replace(rows)``, rows being
            ``(passage, vector)`` pairs.
        size: the longest passage in characters.

    Returns:
        The number of passages the index holds afterwards.

    Raises:
        ValueError: a passage still carries a secret after masking, or the
            embedder returned a different number of vectors.
    """
    rows = [p for document in documents for p in passages(document, size)]
    leaking = [row.url for row in rows if leaks(row.text)]
    if leaking:
        raise ValueError(f"passages still carry a secret after masking: {leaking}")
    texts = [row.text for row in rows]
    vectors = await asyncio.to_thread(embedder.embed, texts) if rows else []
    if len(vectors) != len(rows):
        raise ValueError(
            f"embedder returned {len(vectors)} vectors for {len(rows)} passages"
        )
    await store.replace(list(zip(rows, vectors, strict=True)))
    return len(rows)
