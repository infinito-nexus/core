"""Which engine answers a translation, and what that teaches the next one."""

from __future__ import annotations

import asyncio
import time
from collections import Counter

from .errors import EngineRefusedError, MangledTermError, NoBackendError
from .signature import signature

SYSTEM_ONE = "system_one"
PREFERENCE = "preference"
CHOICE_INSTRUCTIONS = "Which engine should answer this translation request?"
MARKUP_CHARACTERS = "[]{}`*()"


def saturated(tally, minimum, share):
    """The engine a signature has settled on, or None while it is still open.

    Args:
        tally: ``{engine: (won, seen)}`` as the history returns it.
        minimum: comparisons a signature needs before a leader counts.
        share: fraction of wins the leader must hold.

    Returns:
        The engine name, or None when too few comparisons exist or no engine
        holds the share.

    A comparison writes one row per offered engine, so an engine's own ``seen``
    already is the comparison count. Summing them would multiply it by the
    field size and settle a signature after a fraction of the evidence.
    """
    comparisons = max((count for _won, count in tally.values()), default=0)
    if comparisons < minimum:
        return None
    leaders = [
        (won / count, engine)
        for engine, (won, count) in sorted(tally.items())
        if count and won / count >= share
    ]
    return max(leaders)[1] if leaders else None


class Router:
    """Routes one translation, and records what the comparison concluded.

    Args:
        engines: ``{name: engine}``; each engine exposes ``translate`` and
            ``serves(source, target)``.
        decider: the System One client, or None to route without one.
        history: the learning log, or None to decide without a record.
        cache: the translation store, or None to answer every request afresh.
        sampler: decides when to compare instead of answering.
        order: the preference order used when no decider is deployed.
        question: the typed-choice question the verdict is asked under.
        saturation: ``(minimum comparisons, winning share)``.
        strategy: ``system_one`` asks the decider which engine answers,
            ``preference`` takes the declared order.
        failures: the failure log, or None to forget an outage at every
            restart.
        failure_threshold: consecutive failures after which an engine leaves
            the candidate set.
        pairs: ``{engine: catalogued pairs}`` stated in the criteria lines.
    """

    def __init__(
        self,
        engines,
        *,
        decider=None,
        history=None,
        cache=None,
        sampler=None,
        order=(),
        question="translation-verdict",
        saturation=(10, 0.8),
        strategy=PREFERENCE,
        failures=None,
        failure_threshold=3,
        pairs=None,
    ):
        self._engines = dict(engines)
        self._decider = decider
        self._history = history
        self._cache = cache
        self._sampler = sampler
        self._order = tuple(order)
        self._question = question
        self._saturation = saturation
        self._strategy = strategy
        self._failures = failures
        self._failure_threshold = failure_threshold
        self._pairs = dict(pairs or {})
        self._latency = {}

    def candidates(self, source, target, exclude=()):
        """The engines that serve this language pair, in preference order.

        Args:
            source: source language code, or None.
            target: target language code.
            exclude: engines the caller has already found wanting for this
                string. A caller that masks its placeholders judges the
                restored answer, which the gateway never sees, so naming the
                engine that failed that judgement is the only way its own
                verdict can reach the candidate set.
        """
        barred = set(exclude)
        serving = [
            name
            for name, engine in self._engines.items()
            if name not in barred and engine.serves(source, target)
        ]
        ranked = [name for name in self._order if name in serving]
        return ranked + sorted(set(serving) - set(ranked))

    async def _tally(self, request_class):
        """What earlier comparisons concluded, empty when the log cannot answer."""
        if self._history is None:
            return {}
        try:
            return await self._history.wins(request_class)
        except Exception:
            return {}

    async def _streaks(self):
        """Consecutive failures per engine, empty when the log cannot answer."""
        if self._failures is None:
            return {}
        try:
            return await self._failures.streaks()
        except Exception:
            return {}

    async def _ask_one(self, engine, source, target, text, protected=(), fmt="text"):
        started = time.monotonic()
        try:
            answer = await asyncio.to_thread(
                self._engines[engine].translate, source, target, text, protected, fmt
            )
        except Exception as exc:
            await self._failed(engine)
            raise EngineRefusedError(f"{engine} refused the request: {exc}") from exc
        self._latency[engine] = int((time.monotonic() - started) * 1000)
        await self._cleared(engine)
        return answer

    async def _failed(self, engine):
        if self._failures is None:
            return
        try:
            await self._failures.failed(engine)
        except Exception:
            return

    async def _cleared(self, engine):
        if self._failures is None:
            return
        try:
            await self._failures.cleared(engine)
        except Exception:
            return

    def _criteria(self, offered, tally):
        """One line per engine, stating only measured or catalogued facts."""
        criteria = {}
        for engine in offered:
            facts = ["runs in this cluster"]
            pairs = self._pairs.get(engine)
            facts.append(
                f"serves {len(pairs)} catalogued language pairs"
                if pairs
                else "declares no language catalogue"
            )
            if engine in self._latency:
                facts.append(f"answered the last request in {self._latency[engine]} ms")
            won, seen = tally.get(engine, (0, 0))
            if seen:
                facts.append(f"won {won} of {seen} comparisons like this")
            criteria[engine] = "; ".join(facts)
        return criteria

    async def _choose(self, offered, tally, source, target, text):
        """The engine the decider picks, or None when it did not pick one.

        A choice naming an engine that was not offered is refused rather than
        routed to: the options are the gateway's candidate set, and anything
        outside it is an answer to a question nobody asked.
        """
        if self._decider is None or len(offered) < 2:
            return None
        state = f"{source or 'auto'} to {target}: {text}"
        try:
            answer = await asyncio.to_thread(
                self._decider.ask,
                state,
                self._question,
                CHOICE_INSTRUCTIONS,
                self._criteria(offered, tally),
            )
        except Exception:
            return None
        choice = (answer or {}).get("choice")
        return choice if choice in offered else None

    async def translate(
        self, source, target, text, *, protected=(), fmt="text", exclude=()
    ):
        """Translate *text*, comparing engines when the sampler says so.

        Args:
            source: source language code, or None for an undeclared one.
            target: target language code.
            text: the string to translate.
            protected: glossary terms the answer has to keep; they are handed
                to every engine that takes them and checked before the answer
                is cached.
            fmt: the payload format every engine is asked with, ``text`` or
                ``html``.
            exclude: engines the caller already rejected for this string.

        Returns:
            ``(engine, translation)``.

        Raises:
            NoBackendError: when no engine serves the pair, or every engine
                that does refused the request.
            MangledTermError: when every engine dropped a protected term.

        An engine whose failure streak reached the threshold leaves the
        candidate set, but every engine being over it means an outage rather
        than a verdict on the engines: keeping the filter there would answer no
        request ever again, and nothing would clear a streak because nothing
        would be asked.
        """
        serving = self.candidates(source, target, exclude)
        if not serving:
            raise NoBackendError(f"no engine serves {source or 'auto'} to {target}")

        streaks = await self._streaks()
        offered = [
            engine
            for engine in serving
            if streaks.get(engine, 0) < self._failure_threshold
        ]
        offered = offered or serving

        request_class = signature(source, target, text)
        tally = await self._tally(request_class)

        settled = saturated(tally, *self._saturation)
        comparing = (
            len(offered) > 1
            and settled is None
            and self._decider is not None
            and self._sampler is not None
            and self._sampler.due()
        )
        if comparing:
            return await self._compare(
                offered, request_class, source, target, text, protected, fmt
            )

        chosen = settled
        if chosen is None and self._strategy == SYSTEM_ONE:
            chosen = await self._choose(offered, tally, source, target, text)
        return await self._serve(
            chosen or offered[0], offered, source, target, text, protected, fmt
        )

    @staticmethod
    def _mangled(answer, protected, text=""):
        """What *answer* broke: protected terms it lost, then the markup.

        The markup skeleton is checked as a multiset of ``MARKUP_CHARACTERS``
        rather than term presence, because the damage that matters is a count
        that moved: an engine that renders ``**Raw / Community**`` as
        ``**/ Community** *`` keeps every character and still emits a stray
        emphasis marker. Catching it here is what lets the caller's next
        engine be tried, which is the whole reason the candidate set exists.
        """
        lost = [term for term in protected if term not in answer]
        if text and Counter(
            character for character in answer if character in MARKUP_CHARACTERS
        ) != Counter(character for character in text if character in MARKUP_CHARACTERS):
            lost.append("the markup skeleton")
        return lost

    async def _serve(
        self, engine, offered, source, target, text, protected=(), fmt="text"
    ):
        refused = []
        mangled = []
        for name in [engine, *[o for o in offered if o != engine]]:
            cached = await self._cached(name, source, target, text, fmt)
            if cached is not None:
                return name, cached
            try:
                answer = await self._ask_one(name, source, target, text, protected, fmt)
            except EngineRefusedError as exc:
                refused.append(str(exc))
                continue
            missing = self._mangled(answer, protected, text)
            if missing:
                mangled.append(f"{name} dropped {', '.join(missing)}")
                continue
            await self._store(name, source, target, text, answer, fmt)
            return name, answer
        if mangled and not refused:
            raise MangledTermError("; ".join(mangled))
        raise NoBackendError(
            "; ".join(refused + mangled) or "every engine refused the request"
        )

    async def _compare(
        self, offered, request_class, source, target, text, protected=(), fmt="text"
    ):
        replies = {}
        mangled = []
        for name in offered:
            try:
                answer = await self._ask_one(name, source, target, text, protected, fmt)
            except EngineRefusedError:
                continue
            missing = self._mangled(answer, protected, text)
            if missing:
                mangled.append(f"{name} dropped {', '.join(missing)}")
                continue
            replies[name] = answer
        if not replies and mangled:
            raise MangledTermError("; ".join(mangled))
        if not replies:
            raise NoBackendError("every engine refused the request")
        if len(replies) == 1:
            winner, judged = next(iter(replies)), True
        else:
            verdict = await self._judged(text, replies)
            judged = verdict is not None
            winner = verdict or next(
                (name for name in self._order if name in replies), next(iter(replies))
            )
        for name, answer in replies.items():
            await self._store(name, source, target, text, answer, fmt)
        if judged:
            await self._record(request_class, winner, sorted(replies))
        return winner, replies[winner]

    async def _judged(self, text, replies):
        """The engine the decider preferred, or None when it did not say.

        A decider that times out must not fail a request whose translations
        are already in hand: ``_choose`` degrades the same way, and leaving
        this call unguarded turned a slow decider into a 500 that threw the
        replies away. None is the answer in that case rather than a stand-in,
        because the caller records a row only for a verdict that was taken:
        charging the fallback engine a win the decider never awarded would
        let ``saturated`` freeze a signature on the configured order.
        """
        try:
            winner = await asyncio.to_thread(
                self._decider.judge_answers, text, replies, self._question
            )
        except Exception:
            return None
        return winner if winner in replies else None

    async def _record(self, request_class, winner, offered):
        if self._history is None:
            return
        try:
            await self._history.record(request_class, winner, offered)
        except Exception:
            return

    async def _cached(self, engine, source, target, text, fmt="text"):
        if self._cache is None:
            return None
        try:
            return await self._cache.get(engine, source, target, text, fmt)
        except Exception:
            return None

    async def _store(self, engine, source, target, text, answer, fmt="text"):
        if self._cache is None:
            return
        try:
            await self._cache.set(engine, source, target, text, answer, fmt)
        except Exception:
            return
