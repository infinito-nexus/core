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

    async def translate(self, source, target, text):
        """Translate *text*, preferring a reviewed human string.

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

        return await self._router.translate(
            source, target, text, protected=await self._protected(target, text)
        )
