"""The routing guarantees, one class each.

The decision reads earlier outcomes, the verdict is blind to the engine, a
saturated signature skips the decider, an unreadable log does not fail a
request, a cached answer reaches no engine, a repeatedly failing engine leaves
the candidate set, a choice outside the offer is refused, and no reachable
backend fails loudly.
"""

from __future__ import annotations

import asyncio
import unittest

from . import ERRORS, ROUTER

Router = ROUTER.Router
saturated = ROUTER.saturated
NoBackendError = ERRORS.NoBackendError


class FakeEngine:
    def __init__(self, reply, *, pairs=None, raises=None, keeps_terms=True):
        self.reply = reply
        self.pairs = pairs
        self.raises = raises
        self.keeps_terms = keeps_terms
        self.calls = 0
        self.protected = []

    def serves(self, source, target):
        return self.pairs is None or (source, target) in self.pairs

    def translate(self, source, target, text, protected=()):
        self.calls += 1
        self.protected.append(tuple(protected))
        if self.raises:
            raise self.raises
        kept = " ".join(protected) if self.keeps_terms else ""
        return f"{self.reply}:{text}{(' ' + kept) if kept else ''}"


class FakeDecider:
    def __init__(self, pick=None):
        self.pick = pick
        self.seen = []

    def judge_answers(self, text, replies, question):
        self.seen.append((text, dict(replies), question))
        return self.pick or min(replies)


class FakeHistory:
    def __init__(self, tally=None, *, wins_raises=None, record_raises=None):
        self._tally = tally or {}
        self.wins_raises = wins_raises
        self.record_raises = record_raises
        self.recorded = []

    async def wins(self, request_class):
        if self.wins_raises:
            raise self.wins_raises
        return dict(self._tally)

    async def record(self, request_class, winner, offered):
        if self.record_raises:
            raise self.record_raises
        self.recorded.append((request_class, winner, tuple(offered)))


class AlwaysSampler:
    def due(self):
        return True


class NeverSampler:
    def due(self):
        return False


def run(coro):
    return asyncio.run(coro)


class SaturationTestCase(unittest.TestCase):
    def test_too_few_comparisons_leave_the_signature_open(self) -> None:
        self.assertIsNone(saturated({"a": (4, 5)}, 10, 0.8))

    def test_a_clear_leader_over_the_minimum_settles_it(self) -> None:
        self.assertEqual(saturated({"a": (9, 10), "b": (1, 10)}, 10, 0.8), "a")

    def test_a_split_field_stays_open(self) -> None:
        self.assertIsNone(saturated({"a": (6, 10), "b": (6, 10)}, 10, 0.8))

    def test_an_empty_log_stays_open(self) -> None:
        self.assertIsNone(saturated({}, 10, 0.8))


class SaturatedSignatureSkipsTheDeciderTestCase(unittest.TestCase):
    def test_the_settled_engine_answers_and_the_decider_is_never_asked(self) -> None:
        alpha, beta = FakeEngine("alpha"), FakeEngine("beta")
        decider = FakeDecider()
        router = Router(
            {"alpha": alpha, "beta": beta},
            decider=decider,
            history=FakeHistory({"beta": (9, 10), "alpha": (1, 10)}),
            sampler=AlwaysSampler(),
            saturation=(10, 0.8),
        )

        engine, answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual((engine, answer), ("beta", "beta:Haus"))
        self.assertEqual(decider.seen, [], "a settled signature must not be judged")
        self.assertEqual(alpha.calls, 0, "the loser must not even be called")

    def test_an_open_signature_is_compared(self) -> None:
        decider = FakeDecider(pick="beta")
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=decider,
            history=FakeHistory({"alpha": (1, 2)}),
            sampler=AlwaysSampler(),
            saturation=(10, 0.8),
        )

        engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "beta")
        self.assertEqual(len(decider.seen), 1)


class VerdictIsBlindTestCase(unittest.TestCase):
    def test_the_decider_receives_the_replies_and_no_engine_name(self) -> None:
        decider = FakeDecider(pick="alpha")
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=decider,
            history=FakeHistory(),
            sampler=AlwaysSampler(),
        )

        run(router.translate("de", "en", "Haus"))

        _text, replies, _question = decider.seen[0]
        self.assertEqual(sorted(replies), ["alpha", "beta"])

    def test_the_decider_is_asked_under_the_configured_question(self) -> None:
        decider = FakeDecider(pick="alpha")
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=decider,
            history=FakeHistory(),
            sampler=AlwaysSampler(),
            question="which-translation",
        )

        run(router.translate("de", "en", "Haus"))

        self.assertEqual(decider.seen[0][2], "which-translation")


class TheLogRecordsWhatWasOfferedTestCase(unittest.TestCase):
    def test_one_record_names_the_winner_and_everything_offered(self) -> None:
        history = FakeHistory()
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=FakeDecider(pick="beta"),
            history=history,
            sampler=AlwaysSampler(),
        )

        run(router.translate("de", "en", "Haus"))

        self.assertEqual(len(history.recorded), 1)
        request_class, winner, offered = history.recorded[0]
        self.assertEqual((winner, offered), ("beta", ("alpha", "beta")))
        self.assertTrue(request_class.startswith("de:en:"))

    def test_serving_without_a_comparison_writes_no_row(self) -> None:
        history = FakeHistory()
        router = Router(
            {"alpha": FakeEngine("alpha")},
            decider=FakeDecider(),
            history=history,
            sampler=NeverSampler(),
        )

        run(router.translate("de", "en", "Haus"))

        self.assertEqual(history.recorded, [])


class AnUnreadableLogDoesNotFailTheRequestTestCase(unittest.TestCase):
    def test_a_raising_read_still_answers(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha")},
            decider=FakeDecider(),
            history=FakeHistory(wins_raises=RuntimeError("log is down")),
            sampler=NeverSampler(),
        )

        self.assertEqual(
            run(router.translate("de", "en", "Haus")), ("alpha", "alpha:Haus")
        )

    def test_a_raising_write_still_answers(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=FakeDecider(pick="alpha"),
            history=FakeHistory(record_raises=RuntimeError("log is down")),
            sampler=AlwaysSampler(),
        )

        engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "alpha")


class NoBackendFailsLoudlyTestCase(unittest.TestCase):
    def test_no_engine_serving_the_pair_raises(self) -> None:
        router = Router({"alpha": FakeEngine("alpha", pairs=[("de", "fr")])})

        with self.assertRaises(NoBackendError) as caught:
            run(router.translate("de", "en", "Haus"))

        self.assertIn("no engine serves", str(caught.exception))

    def test_every_engine_refusing_raises_instead_of_echoing_the_source(self) -> None:
        router = Router(
            {
                "alpha": FakeEngine("alpha", raises=OSError("unreachable")),
                "beta": FakeEngine("beta", raises=OSError("unreachable")),
            },
            sampler=NeverSampler(),
        )

        with self.assertRaises(NoBackendError) as caught:
            run(router.translate("de", "en", "Haus"))

        self.assertNotIn("Haus", str(caught.exception).replace("unreachable", ""))

    def test_one_refusing_engine_is_routed_around(self) -> None:
        beta = FakeEngine("beta")
        router = Router(
            {"alpha": FakeEngine("alpha", raises=OSError("down")), "beta": beta},
            order=("alpha", "beta"),
            sampler=NeverSampler(),
        )

        self.assertEqual(
            run(router.translate("de", "en", "Haus")), ("beta", "beta:Haus")
        )

    def test_a_refusing_engine_is_dropped_from_a_comparison_without_a_loss(
        self,
    ) -> None:
        history = FakeHistory()
        router = Router(
            {
                "alpha": FakeEngine("alpha"),
                "beta": FakeEngine("beta", raises=OSError()),
            },
            decider=FakeDecider(),
            history=history,
            sampler=AlwaysSampler(),
        )

        engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "alpha")
        self.assertEqual(history.recorded[0][2], ("alpha",), "a failure is not a loss")


class FakeFailureLog:
    def __init__(self, streaks=None, *, raises=None):
        self._streaks = streaks or {}
        self.raises = raises
        self.failed_engines: list[str] = []
        self.cleared_engines: list[str] = []

    async def streaks(self):
        if self.raises:
            raise self.raises
        return dict(self._streaks)

    async def failed(self, engine):
        self.failed_engines.append(engine)

    async def cleared(self, engine):
        self.cleared_engines.append(engine)


class FakeChoiceDecider:
    def __init__(self, choice):
        self.choice = choice
        self.asked: list[tuple] = []

    def ask(self, state, question, instructions, criteria):
        self.asked.append((state, question, instructions, dict(criteria)))
        return {"choice": self.choice}


class FailingEngineLeavesTheCandidateSetTestCase(unittest.TestCase):
    def test_an_engine_over_the_threshold_is_not_asked(self) -> None:
        alpha, beta = FakeEngine("alpha"), FakeEngine("beta")
        router = Router(
            {"alpha": alpha, "beta": beta},
            order=("alpha", "beta"),
            failures=FakeFailureLog({"alpha": 3}),
            failure_threshold=3,
            sampler=NeverSampler(),
        )

        engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "beta")
        self.assertEqual(alpha.calls, 0, "a dropped engine must not be called")

    def test_an_engine_below_the_threshold_still_answers(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            order=("alpha", "beta"),
            failures=FakeFailureLog({"alpha": 2}),
            failure_threshold=3,
            sampler=NeverSampler(),
        )

        self.assertEqual(run(router.translate("de", "en", "Haus"))[0], "alpha")

    def test_every_engine_over_the_threshold_keeps_the_whole_set(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            order=("alpha", "beta"),
            failures=FakeFailureLog({"alpha": 9, "beta": 9}),
            failure_threshold=3,
            sampler=NeverSampler(),
        )

        self.assertEqual(run(router.translate("de", "en", "Haus"))[0], "alpha")

    def test_a_failure_is_counted_and_an_answer_clears_the_streak(self) -> None:
        log = FakeFailureLog()
        router = Router(
            {
                "alpha": FakeEngine("alpha", raises=OSError("down")),
                "beta": FakeEngine("beta"),
            },
            order=("alpha", "beta"),
            failures=log,
            sampler=NeverSampler(),
        )

        run(router.translate("de", "en", "Haus"))

        self.assertEqual(log.failed_engines, ["alpha"])
        self.assertEqual(log.cleared_engines, ["beta"])

    def test_an_unreadable_failure_log_does_not_fail_the_request(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha")},
            failures=FakeFailureLog(raises=OSError("log gone")),
            sampler=NeverSampler(),
        )

        self.assertEqual(run(router.translate("de", "en", "Haus"))[0], "alpha")


class FakeCache:
    def __init__(self, stored=None):
        self.stored = dict(stored or {})
        self.reads = 0

    async def get(self, engine, source, target, text):
        self.reads += 1
        return self.stored.get((engine, source, target, text))

    async def set(self, engine, source, target, text, translation):
        self.stored[(engine, source, target, text)] = translation


class CacheTestCase(unittest.TestCase):
    def test_a_repeated_request_is_answered_without_reaching_an_engine(self) -> None:
        alpha = FakeEngine("alpha")
        cache = FakeCache({("alpha", "de", "en", "Haus"): "House"})
        router = Router(
            {"alpha": alpha}, cache=cache, order=("alpha",), sampler=NeverSampler()
        )

        self.assertEqual(run(router.translate("de", "en", "Haus")), ("alpha", "House"))
        self.assertEqual(alpha.calls, 0, "a cached answer must not call the engine")

    def test_a_new_request_is_stored_under_its_engine(self) -> None:
        cache = FakeCache()
        router = Router(
            {"alpha": FakeEngine("alpha")},
            cache=cache,
            order=("alpha",),
            sampler=NeverSampler(),
        )

        run(router.translate("de", "en", "Haus"))

        self.assertEqual(cache.stored[("alpha", "de", "en", "Haus")], "alpha:Haus")

    def test_an_unreadable_cache_does_not_fail_the_request(self) -> None:
        class Broken:
            async def get(self, *_args):
                raise OSError("cache gone")

            async def set(self, *_args):
                raise OSError("cache gone")

        router = Router(
            {"alpha": FakeEngine("alpha")},
            cache=Broken(),
            order=("alpha",),
            sampler=NeverSampler(),
        )

        self.assertEqual(
            run(router.translate("de", "en", "Haus")), ("alpha", "alpha:Haus")
        )


class GlossaryTestCase(unittest.TestCase):
    def test_the_terms_reach_every_engine_that_is_asked(self) -> None:
        alpha = FakeEngine("alpha")
        router = Router({"alpha": alpha}, order=("alpha",), sampler=NeverSampler())

        run(router.translate("en", "de", "House", protected=("Nextcloud",)))

        self.assertEqual(alpha.protected, [("Nextcloud",)])

    def test_a_mangled_answer_is_refused_and_never_cached(self) -> None:
        cache = FakeCache()
        router = Router(
            {"alpha": FakeEngine("alpha", keeps_terms=False)},
            cache=cache,
            order=("alpha",),
            sampler=NeverSampler(),
        )

        with self.assertRaises(ERRORS.MangledTermError):
            run(router.translate("en", "de", "House", protected=("Nextcloud",)))

        self.assertEqual(cache.stored, {}, "a mangled answer must not be cached")

    def test_an_engine_that_keeps_the_term_answers_instead(self) -> None:
        keeper = FakeEngine("beta")
        router = Router(
            {"alpha": FakeEngine("alpha", keeps_terms=False), "beta": keeper},
            order=("alpha", "beta"),
            sampler=NeverSampler(),
        )

        engine, answer = run(
            router.translate("en", "de", "House", protected=("Nextcloud",))
        )

        self.assertEqual(engine, "beta")
        self.assertIn("Nextcloud", answer)

    def test_a_mangled_reply_never_enters_a_comparison(self) -> None:
        history = FakeHistory()
        router = Router(
            {
                "alpha": FakeEngine("alpha", keeps_terms=False),
                "beta": FakeEngine("beta"),
            },
            decider=FakeDecider(),
            history=history,
            sampler=AlwaysSampler(),
        )

        engine, _answer = run(
            router.translate("en", "de", "House", protected=("Nextcloud",))
        )

        self.assertEqual(engine, "beta")
        self.assertEqual(history.recorded[0][2], ("beta",))


class EngineChoiceTestCase(unittest.TestCase):
    def test_the_decider_picks_which_engine_answers(self) -> None:
        decider = FakeChoiceDecider("beta")
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=decider,
            history=FakeHistory({"beta": (1, 2)}),
            order=("alpha", "beta"),
            sampler=NeverSampler(),
            strategy=ROUTER.SYSTEM_ONE,
        )

        engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "beta")
        _state, _question, _instructions, criteria = decider.asked[0]
        self.assertEqual(sorted(criteria), ["alpha", "beta"])
        self.assertIn("won 1 of 2 comparisons like this", criteria["beta"])

    def test_a_choice_outside_the_offer_is_refused(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=FakeChoiceDecider("deepl"),
            history=FakeHistory(),
            order=("alpha", "beta"),
            sampler=NeverSampler(),
            strategy=ROUTER.SYSTEM_ONE,
        )

        engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "alpha", "an unoffered engine is never routed to")

    def test_the_preference_strategy_never_asks(self) -> None:
        decider = FakeChoiceDecider("beta")
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=decider,
            history=FakeHistory(),
            order=("alpha", "beta"),
            sampler=NeverSampler(),
            strategy=ROUTER.PREFERENCE,
        )

        engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "alpha")
        self.assertEqual(decider.asked, [])

    def test_a_decider_that_cannot_answer_falls_back_to_the_order(self) -> None:
        class Unreachable:
            def ask(self, *_args):
                raise OSError("decider down")

        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=Unreachable(),
            history=FakeHistory(),
            order=("beta", "alpha"),
            sampler=NeverSampler(),
            strategy=ROUTER.SYSTEM_ONE,
        )

        self.assertEqual(run(router.translate("de", "en", "Haus"))[0], "beta")


if __name__ == "__main__":
    unittest.main()
