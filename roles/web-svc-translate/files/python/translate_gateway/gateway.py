"""What answers a translation request, in the order the answer is trusted."""

from __future__ import annotations

import asyncio

REVIEWED = "weblate"


class Gateway:
    """Translation memory first, then the router, then a loud failure.

    Args:
        router: the engine router, asked only when no reviewed string exists.
        memory: the translation memory, or None when Weblate is not deployed.
        glossary: terms that must survive a translation, or None.
    """

    def __init__(self, router, *, memory=None, glossary=None):
        self._router = router
        self._memory = memory
        self._glossary = glossary

    async def _reviewed(self, target, text):
        """The reviewed translation of *text*, or None.

        A memory that cannot answer is not an error: the request falls through
        to the engines, which is worse than a reviewed string and better than
        no answer at all.
        """
        if self._memory is None:
            return None
        try:
            return await asyncio.to_thread(self._memory.reviewed, target, text)
        except Exception:
            return None

    async def _protected(self, target, text):
        if self._glossary is None:
            return ()
        try:
            return tuple(await asyncio.to_thread(self._glossary.terms, target, text))
        except Exception:
            return ()

    async def translate(
        self, source, target, text, *, fmt="text", protected=(), exclude=()
    ):
        """Translate *text*, preferring a reviewed human string.

        Args:
            source: source language code, or None for auto-detection.
            target: target language code.
            text: the string to translate.
            fmt: the payload format the engines are asked with, ``text`` or
                ``html``.
            protected: spans the caller needs back verbatim, on top of the
                glossary. A caller that masks its placeholders knows which
                tokens must survive and the glossary does not.
            exclude: engines the caller already rejected for this string.
                A reviewed string still wins over all of them, because the
                precedence rule is about who wrote the translation, not about
                which engine last disappointed the caller.

        Returns:
            ``(origin, translation)`` where origin is ``weblate`` or the
            engine name.

        Raises:
            NoBackendError: when no engine could answer and no reviewed
                string exists.
            MangledTermError: when every engine dropped a protected term.

        The glossary terms travel with the request rather than being checked
        on the way back, because the router is what caches an answer: a check
        here would run after the cache already holds the mangled string.
        """
        reviewed = await self._reviewed(target, text)
        if reviewed:
            return REVIEWED, reviewed

        terms = (*await self._protected(target, text), *protected)
        return await self._router.translate(
            source, target, text, protected=terms, fmt=fmt, exclude=exclude
        )
