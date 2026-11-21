"""The routing guarantees, one class each.

The decision reads earlier outcomes, the verdict is blind to the engine, a
saturated signature skips the decider, an unreadable log does not fail a
request, a cached answer reaches no engine, a repeatedly failing engine leaves
the candidate set, a choice outside the offer is refused, and no reachable
backend fails loudly.
"""

from __future__ import annotations

import ast
import asyncio
import unittest

from utils.cache.files import read_text

from . import ERRORS, LEDGER, PACKAGE_DIR, ROUTER

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
        self.formats = []

    def serves(self, source, target):
        return self.pairs is None or (source, target) in self.pairs

    def translate(self, source, target, text, protected=(), fmt="text"):
        self.calls += 1
        self.protected.append(tuple(protected))
        self.formats.append(fmt)
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
    def __init__(
        self, tally=None, *, wins_raises=None, record_raises=None, speeds=None
    ):
        self._tally = tally or {}
        self._speeds = speeds or {}
        self.wins_raises = wins_raises
        self.record_raises = record_raises
        self.recorded = []
        self.timings = []

    async def wins(self, request_class):
        if self.wins_raises:
            raise self.wins_raises
        return dict(self._tally)

    async def speed(self, request_class):
        return dict(self._speeds)

    async def record(self, request_class, winner, offered, took_ms=None):
        if self.record_raises:
            raise self.record_raises
        self.recorded.append((request_class, winner, tuple(offered)))
        self.timings.append(dict(took_ms or {}))


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

    def test_a_leader_no_longer_deployed_is_passed_over(self) -> None:
        engine = FakeEngine("engine")
        router = Router(
            {"libretranslate-engine": engine},
            history=FakeHistory({"libretranslate": (9, 10)}),
            sampler=AlwaysSampler(),
            saturation=(10, 0.8),
        )

        answered, answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(
            (answered, answer),
            ("libretranslate-engine", "engine:Haus"),
            "a history row naming a renamed or removed engine must not fail "
            "the request",
        )

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

    def test_a_decider_that_raises_still_answers_the_request(self) -> None:
        """Its timeout used to reach the caller as a 500, replies and all."""

        class Unreachable:
            def judge_answers(self, *_args):
                raise TimeoutError("timed out")

        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=Unreachable(),
            history=FakeHistory(),
            sampler=AlwaysSampler(),
            order=("beta", "alpha"),
        )

        engine, answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual((engine, answer), ("beta", "beta:Haus"))

    def test_a_round_the_decider_never_judged_is_not_recorded(self) -> None:
        """A fallback winner is not evidence that it translates the pair better."""

        class Unreachable:
            def judge_answers(self, *_args):
                raise TimeoutError("timed out")

        history = FakeHistory()
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=Unreachable(),
            history=history,
            sampler=AlwaysSampler(),
            order=("beta", "alpha"),
        )

        run(router.translate("de", "en", "Haus"))

        self.assertEqual(history.recorded, [])

    def test_a_verdict_naming_an_engine_that_did_not_answer_is_discarded(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=FakeDecider(pick="gamma"),
            history=FakeHistory(),
            sampler=AlwaysSampler(),
            order=("alpha", "beta"),
        )

        engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "alpha")

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
    def __init__(self, streaks=None, *, raises=None, totals=None):
        self._streaks = streaks or {}
        self._totals = totals or {}
        self.raises = raises
        self.failed_engines: list[str] = []
        self.cleared_engines: list[str] = []

    async def streaks(self):
        if self.raises:
            raise self.raises
        return dict(self._streaks)

    async def counts(self):
        if self.raises:
            raise self.raises
        return {
            engine: (self._streaks.get(engine, 0), total)
            for engine, total in self._totals.items()
        }

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

    @staticmethod
    def key(engine, source, target, text, protected=()):
        return (engine, source, target, text, *sorted(set(protected)))

    async def get(self, engine, source, target, text, fmt="text", protected=()):
        self.reads += 1
        return self.stored.get(self.key(engine, source, target, text, protected))

    async def set(
        self, engine, source, target, text, translation, fmt="text", protected=()
    ):
        self.stored[self.key(engine, source, target, text, protected)] = translation


class CacheTestCase(unittest.TestCase):
    def test_a_repeated_request_is_answered_without_reaching_an_engine(self) -> None:
        alpha = FakeEngine("alpha")
        cache = FakeCache({("alpha", "de", "en", "Haus"): "House"})
        router = Router(
            {"alpha": alpha}, cache=cache, order=("alpha",), sampler=NeverSampler()
        )

        self.assertEqual(run(router.translate("de", "en", "Haus")), ("alpha", "House"))
        self.assertEqual(alpha.calls, 0, "a cached answer must not call the engine")

    def test_an_engine_that_moves_an_emphasis_marker_is_passed_over(self) -> None:
        """The count is what moves; every character is still present."""

        class Stray:
            name = "stray"
            pairs = frozenset()

            def serves(self, *_args):
                return True

            def translate(self, _source, _target, text, _protected=(), _fmt="text"):
                return text.replace("**Raw**", "**/ Raw** *")

        router = Router(
            {"stray": Stray(), "beta": FakeEngine("beta")},
            order=("stray", "beta"),
            sampler=NeverSampler(),
        )

        engine, _answer = run(router.translate("en", "de", "The **Raw** edition"))

        self.assertEqual(engine, "beta")

    def test_an_engine_that_adds_a_preamble_line_is_passed_over_and_not_cached(
        self,
    ) -> None:
        class Chatty:
            name = "chatty"
            pairs = frozenset()

            def serves(self, *_args):
                return True

            def translate(self, _source, _target, text, _protected=(), _fmt="text"):
                return f"Translation of the text to German:\n\n{text}"

        cache = FakeCache()
        router = Router(
            {"chatty": Chatty(), "beta": FakeEngine("beta")},
            cache=cache,
            order=("chatty", "beta"),
            sampler=NeverSampler(),
        )

        engine, _answer = run(router.translate("en", "de", "Shared storage"))

        self.assertEqual(engine, "beta")
        self.assertNotIn(("chatty", "en", "de", "Shared storage"), cache.stored)

    def test_a_line_break_the_source_carries_is_served(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha")}, order=("alpha",), sampler=NeverSampler()
        )

        engine, answer = run(router.translate("en", "de", "First\nSecond"))

        self.assertEqual((engine, answer), ("alpha", "alpha:First\nSecond"))

    def test_an_excluded_engine_is_not_asked(self) -> None:
        """The caller judges the restored answer the gateway never sees."""
        alpha = FakeEngine("alpha")
        router = Router(
            {"alpha": alpha, "beta": FakeEngine("beta")},
            order=("alpha", "beta"),
            sampler=NeverSampler(),
        )

        engine, _answer = run(router.translate("en", "de", "House", exclude=("alpha",)))

        self.assertEqual(engine, "beta")
        self.assertEqual(alpha.calls, 0)

    def test_excluding_every_engine_fails_loudly(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha")}, order=("alpha",), sampler=NeverSampler()
        )

        with self.assertRaises(NoBackendError):
            run(router.translate("en", "de", "House", exclude=("alpha",)))

    def test_a_translation_that_keeps_the_markup_is_served(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha")}, order=("alpha",), sampler=NeverSampler()
        )

        engine, _answer = run(router.translate("en", "de", "plain prose"))

        self.assertEqual(engine, "alpha")

    def test_the_requested_format_reaches_the_engine(self) -> None:
        alpha = FakeEngine("alpha")
        router = Router({"alpha": alpha}, order=("alpha",), sampler=NeverSampler())

        run(router.translate("en", "de", '<x id="0"></x>', fmt="html"))

        self.assertEqual(alpha.formats, ["html"])

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


def _strategy_argument(source: str) -> ast.expr:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Router":
            for keyword in node.keywords:
                if keyword.arg == "strategy":
                    return keyword.value
    raise AssertionError("no Router(...) call with a strategy keyword")


def _reads_the_variable_without_fallback(value: ast.expr) -> bool:
    return (
        isinstance(value, ast.Subscript)
        and ast.unparse(value.value) == "os.environ"
        and ast.literal_eval(value.slice) == "TRANSLATE_ROUTER_STRATEGY"
    )


class StrategyHasNoFallbackTestCase(unittest.TestCase):
    def test_the_deployed_gateway_reads_the_strategy_without_a_fallback(self) -> None:
        value = _strategy_argument(read_text(str(PACKAGE_DIR / "asgi.py")))

        self.assertTrue(_reads_the_variable_without_fallback(value), ast.unparse(value))

    def test_red_fixture_a_fallback_value_is_caught(self) -> None:
        for source in (
            'Router(strategy=os.environ.get("TRANSLATE_ROUTER_STRATEGY") or "x")',
            'Router(strategy=os.environ.get("TRANSLATE_ROUTER_STRATEGY", "x"))',
        ):
            with self.subTest(source=source):
                self.assertFalse(
                    _reads_the_variable_without_fallback(_strategy_argument(source))
                )

    def test_an_unknown_strategy_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Router({"alpha": FakeEngine("alpha")}, strategy="prefernce")

    def test_both_declared_strategies_are_accepted(self) -> None:
        for strategy in (ROUTER.SYSTEM_ONE, ROUTER.PREFERENCE):
            with self.subTest(strategy=strategy):
                Router({"alpha": FakeEngine("alpha")}, strategy=strategy)


class AnUnreadableLogIsLoggedTestCase(unittest.TestCase):
    def test_an_unreadable_history_is_logged_and_the_request_answers(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha")},
            decider=FakeDecider(),
            history=FakeHistory(wins_raises=RuntimeError("log is down")),
            sampler=NeverSampler(),
        )

        with self.assertLogs(LEDGER.LOGGER, level="WARNING") as logged:
            answered = run(router.translate("de", "en", "Haus"))

        self.assertEqual(answered, ("alpha", "alpha:Haus"))
        self.assertIn("learning log could not be read", "\n".join(logged.output))
        self.assertIn("RuntimeError", "\n".join(logged.output))

    def test_the_warning_carries_no_value_the_store_echoed(self) -> None:
        """A database error can echo its arguments, and those carry the text."""

        class Echoing:
            async def get(self, *args):
                raise ValueError(f"invalid input for query argument $1: {args!r}")

            async def set(self, *args):
                raise ValueError(f"invalid input for query argument $2: {args!r}")

        router = Router(
            {"alpha": FakeEngine("alpha")},
            cache=Echoing(),
            history=FakeHistory(wins_raises=RuntimeError("row Patient Smith")),
            order=("alpha",),
            sampler=NeverSampler(),
        )

        with self.assertLogs(LEDGER.LOGGER, level="WARNING") as logged:
            run(router.translate("de", "en", "Patient Smith"))

        output = "\n".join(logged.output)
        self.assertIn("the cache could not be read", output)
        self.assertIn("the cache could not be written", output)
        self.assertIn("ValueError", output)
        self.assertNotIn("Patient Smith", output)

    def test_an_unwritable_history_is_logged_and_the_request_answers(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=FakeDecider(pick="alpha"),
            history=FakeHistory(record_raises=RuntimeError("disk full")),
            sampler=AlwaysSampler(),
        )

        with self.assertLogs(LEDGER.LOGGER, level="WARNING") as logged:
            engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "alpha")
        self.assertIn("learning log could not be written", "\n".join(logged.output))

    def test_an_unreadable_failure_log_is_logged(self) -> None:
        router = Router(
            {"alpha": FakeEngine("alpha")},
            failures=FakeFailureLog(raises=OSError("log gone")),
            sampler=NeverSampler(),
        )

        with self.assertLogs(LEDGER.LOGGER, level="WARNING") as logged:
            run(router.translate("de", "en", "Haus"))

        self.assertIn("failure log could not be read", "\n".join(logged.output))


class CountingSampler:
    def __init__(self, due):
        self._due = due
        self.asked = 0

    def due(self):
        self.asked += 1
        return self._due


SETTLED_ON_BETA = {"beta": (9, 10), "alpha": (1, 10)}


class ResampleTestCase(unittest.TestCase):
    def test_a_due_resampler_puts_a_settled_signature_to_a_comparison(self) -> None:
        """Without it a verdict the engines have outgrown would hold for good."""
        alpha, beta = FakeEngine("alpha"), FakeEngine("beta")
        decider = FakeDecider(pick="alpha")
        history = FakeHistory(SETTLED_ON_BETA)
        router = Router(
            {"alpha": alpha, "beta": beta},
            decider=decider,
            history=history,
            sampler=NeverSampler(),
            resampler=AlwaysSampler(),
            saturation=(10, 0.8),
        )

        engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "alpha")
        self.assertEqual(len(decider.seen), 1, "the re-opened signature is judged")
        self.assertEqual(history.recorded[0][1:], ("alpha", ("alpha", "beta")))

    def test_a_resampler_that_is_not_due_leaves_the_leader_answering(self) -> None:
        alpha = FakeEngine("alpha")
        decider = FakeDecider()
        router = Router(
            {"alpha": alpha, "beta": FakeEngine("beta")},
            decider=decider,
            history=FakeHistory(SETTLED_ON_BETA),
            sampler=AlwaysSampler(),
            resampler=NeverSampler(),
            saturation=(10, 0.8),
        )

        engine, _answer = run(router.translate("de", "en", "Haus"))

        self.assertEqual(engine, "beta")
        self.assertEqual(decider.seen, [])
        self.assertEqual(alpha.calls, 0)

    def test_an_open_signature_asks_the_sampler_not_the_resampler(self) -> None:
        sampler, resampler = CountingSampler(False), CountingSampler(True)
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=FakeDecider(),
            history=FakeHistory({"alpha": (1, 2)}),
            sampler=sampler,
            resampler=resampler,
            saturation=(10, 0.8),
        )

        run(router.translate("de", "en", "Haus"))

        self.assertEqual((sampler.asked, resampler.asked), (1, 0))

    def test_a_settled_signature_asks_the_resampler_not_the_sampler(self) -> None:
        sampler, resampler = CountingSampler(True), CountingSampler(False)
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=FakeDecider(),
            history=FakeHistory(SETTLED_ON_BETA),
            sampler=sampler,
            resampler=resampler,
            saturation=(10, 0.8),
        )

        run(router.translate("de", "en", "Haus"))

        self.assertEqual((sampler.asked, resampler.asked), (0, 1))


class ACachedAnswerReachesNoEngineInAComparisonTestCase(unittest.TestCase):
    def test_a_comparison_judges_the_cached_answers_without_asking_again(self) -> None:
        alpha, beta = FakeEngine("alpha"), FakeEngine("beta")
        decider = FakeDecider(pick="beta")
        cache = FakeCache(
            {
                ("alpha", "de", "en", "Haus"): "House",
                ("beta", "de", "en", "Haus"): "Home",
            }
        )
        router = Router(
            {"alpha": alpha, "beta": beta},
            decider=decider,
            history=FakeHistory(),
            cache=cache,
            sampler=AlwaysSampler(),
        )

        self.assertEqual(run(router.translate("de", "en", "Haus")), ("beta", "Home"))
        self.assertEqual((alpha.calls, beta.calls), (0, 0))
        self.assertEqual(decider.seen[0][1], {"alpha": "House", "beta": "Home"})

    def test_only_the_engine_without_a_cached_answer_is_asked(self) -> None:
        alpha, beta = FakeEngine("alpha"), FakeEngine("beta")
        cache = FakeCache({("alpha", "de", "en", "Haus"): "House"})
        router = Router(
            {"alpha": alpha, "beta": beta},
            decider=FakeDecider(pick="alpha"),
            history=FakeHistory(),
            cache=cache,
            sampler=AlwaysSampler(),
        )

        run(router.translate("de", "en", "Haus"))

        self.assertEqual((alpha.calls, beta.calls), (0, 1))
        self.assertEqual(cache.stored[("beta", "de", "en", "Haus")], "beta:Haus")


class FakeRejectionLog:
    def __init__(self, counts=None, *, raises=None):
        self._counts = counts or {}
        self.raises = raises
        self.rejected_answers: list[tuple] = []

    async def rejected(self, engine, source, target):
        self.rejected_answers.append((engine, source, target))

    async def counts(self, source, target):
        if self.raises:
            raise self.raises
        return dict(self._counts)


TERM = ("Nextcloud",)
STALE = FakeCache.key("alpha", "en", "de", "Open Nextcloud", TERM)


class AMangledCachedAnswerIsAskedAgainTestCase(unittest.TestCase):
    """A stored answer may predate the check it now fails."""

    def test_a_comparison_judges_the_fresh_answer_not_the_mangled_one(self) -> None:
        alpha, beta = FakeEngine("alpha"), FakeEngine("beta")
        decider, history = FakeDecider(pick="alpha"), FakeHistory()
        cache, rejections = FakeCache({STALE: "Oeffne die Wolke"}), FakeRejectionLog()
        router = Router(
            {"alpha": alpha, "beta": beta},
            decider=decider,
            history=history,
            cache=cache,
            rejections=rejections,
            sampler=AlwaysSampler(),
            order=("alpha", "beta"),
        )

        engine, answer = run(
            router.translate("en", "de", "Open Nextcloud", protected=TERM)
        )

        self.assertEqual(engine, "alpha")
        self.assertIn("Nextcloud", answer)
        self.assertEqual(alpha.calls, 1, "the engine behind the stale row is asked")
        self.assertNotIn("Oeffne die Wolke", decider.seen[0][1].values())
        self.assertEqual(rejections.rejected_answers, [("alpha", "en", "de")])
        self.assertEqual(cache.stored[STALE], answer)

    def test_serving_answers_afresh_instead_of_the_mangled_row(self) -> None:
        alpha, rejections = FakeEngine("alpha"), FakeRejectionLog()
        cache = FakeCache({STALE: "Oeffne die Wolke"})
        router = Router(
            {"alpha": alpha},
            cache=cache,
            rejections=rejections,
            order=("alpha",),
            sampler=NeverSampler(),
        )

        engine, answer = run(
            router.translate("en", "de", "Open Nextcloud", protected=TERM)
        )

        self.assertEqual((engine, alpha.calls), ("alpha", 1))
        self.assertIn("Nextcloud", answer)
        self.assertEqual(rejections.rejected_answers, [("alpha", "en", "de")])
        self.assertEqual(cache.stored[STALE], answer)

    def test_a_cached_answer_that_holds_is_served_without_a_rejection(self) -> None:
        """The control: the check drops only what it would drop fresh."""
        alpha, rejections = FakeEngine("alpha"), FakeRejectionLog()
        cache = FakeCache({STALE: "Oeffne Nextcloud"})
        router = Router(
            {"alpha": alpha},
            cache=cache,
            rejections=rejections,
            order=("alpha",),
            sampler=NeverSampler(),
        )

        answered = run(router.translate("en", "de", "Open Nextcloud", protected=TERM))

        self.assertEqual(answered, ("alpha", "Oeffne Nextcloud"))
        self.assertEqual((alpha.calls, rejections.rejected_answers), (0, []))

    def test_a_new_glossary_term_misses_the_row_stored_without_it(self) -> None:
        alpha = FakeEngine("alpha")
        cache = FakeCache({("alpha", "en", "de", "Open Nextcloud"): "Oeffne Nextcloud"})
        router = Router(
            {"alpha": alpha}, cache=cache, order=("alpha",), sampler=NeverSampler()
        )

        run(router.translate("en", "de", "Open Nextcloud", protected=TERM))

        self.assertEqual(alpha.calls, 1)


class ThreeCountsTestCase(unittest.TestCase):
    """A failure, a rejected answer and a lost comparison each move one count."""

    def _compare(self, engines, protected=()):
        failures, rejections, history = (
            FakeFailureLog(),
            FakeRejectionLog(),
            FakeHistory(),
        )
        router = Router(
            engines,
            decider=FakeDecider(pick="beta"),
            history=history,
            failures=failures,
            rejections=rejections,
            sampler=AlwaysSampler(),
            order=("alpha", "beta"),
        )
        run(router.translate("en", "de", "House", protected=protected))
        return failures, rejections, history

    def test_a_failure_moves_only_the_failure_count(self) -> None:
        failures, rejections, history = self._compare(
            {
                "alpha": FakeEngine("alpha", raises=OSError("down")),
                "beta": FakeEngine("beta"),
            }
        )

        self.assertEqual(failures.failed_engines, ["alpha"])
        self.assertEqual(rejections.rejected_answers, [])
        self.assertNotIn("alpha", history.recorded[0][2])

    def test_a_rejected_answer_moves_only_the_rejection_count(self) -> None:
        failures, rejections, history = self._compare(
            {
                "alpha": FakeEngine("alpha", keeps_terms=False),
                "beta": FakeEngine("beta"),
            },
            protected=("Nextcloud",),
        )

        self.assertEqual(rejections.rejected_answers, [("alpha", "en", "de")])
        self.assertEqual(failures.failed_engines, [])
        self.assertNotIn("alpha", history.recorded[0][2])

    def test_a_lost_comparison_moves_only_the_learning_log(self) -> None:
        failures, rejections, history = self._compare(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")}
        )

        self.assertEqual(history.recorded[0][1:], ("beta", ("alpha", "beta")))
        self.assertEqual(failures.failed_engines, [])
        self.assertEqual(rejections.rejected_answers, [])

    def test_a_rejected_answer_outside_a_comparison_is_counted_too(self) -> None:
        rejections = FakeRejectionLog()
        router = Router(
            {
                "alpha": FakeEngine("alpha", keeps_terms=False),
                "beta": FakeEngine("beta"),
            },
            rejections=rejections,
            order=("alpha", "beta"),
            sampler=NeverSampler(),
        )

        engine, _answer = run(
            router.translate("en", "de", "House", protected=("Nextcloud",))
        )

        self.assertEqual(engine, "beta")
        self.assertEqual(rejections.rejected_answers, [("alpha", "en", "de")])


class TheCriteriaLineTellsTheCountsApartTestCase(unittest.TestCase):
    def _criteria(self, *, failures, rejections, tally):
        decider = FakeChoiceDecider("beta")
        router = Router(
            {"alpha": FakeEngine("alpha"), "beta": FakeEngine("beta")},
            decider=decider,
            history=FakeHistory(tally),
            failures=failures,
            rejections=rejections,
            order=("alpha", "beta"),
            sampler=NeverSampler(),
            strategy=ROUTER.SYSTEM_ONE,
        )
        engine, _answer = run(router.translate("de", "en", "Haus"))
        self.assertEqual(engine, "beta")
        return decider.asked[0][3]

    def test_each_count_has_a_clause_of_its_own(self) -> None:
        criteria = self._criteria(
            failures=FakeFailureLog(totals={"alpha": 2}),
            rejections=FakeRejectionLog({"alpha": 3}),
            tally={"alpha": (1, 4)},
        )

        self.assertIn("won 1 of 4 comparisons like this", criteria["alpha"])
        self.assertIn("failed to answer 2 requests", criteria["alpha"])
        self.assertIn(
            "had 3 answers rejected for this language pair", criteria["alpha"]
        )

    def test_an_engine_without_counts_carries_no_such_clause(self) -> None:
        criteria = self._criteria(
            failures=FakeFailureLog(totals={"alpha": 2}),
            rejections=FakeRejectionLog({"alpha": 3}),
            tally={"alpha": (1, 4)},
        )

        for clause in ("comparisons", "failed", "rejected"):
            with self.subTest(clause=clause):
                self.assertNotIn(clause, criteria["beta"])

    def test_a_single_failure_and_rejection_read_in_the_singular(self) -> None:
        criteria = self._criteria(
            failures=FakeFailureLog(totals={"alpha": 1}),
            rejections=FakeRejectionLog({"alpha": 1}),
            tally={},
        )

        self.assertIn("failed to answer 1 request;", criteria["alpha"] + ";")
        self.assertIn("had 1 answer rejected", criteria["alpha"])

    def test_unreadable_counts_leave_the_decision_standing(self) -> None:
        with self.assertLogs(LEDGER.LOGGER, level="WARNING"):
            criteria = self._criteria(
                failures=FakeFailureLog(raises=OSError("log gone")),
                rejections=FakeRejectionLog(raises=OSError("log gone")),
                tally={},
            )

        self.assertNotIn("failed", criteria["alpha"])
        self.assertNotIn("rejected", criteria["alpha"])


if __name__ == "__main__":
    unittest.main()
