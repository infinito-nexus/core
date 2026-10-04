"""A reviewed human translation outranks every engine, and a mangled term loses."""

from __future__ import annotations

import asyncio
import unittest

from . import ERRORS, GATEWAY

Gateway = GATEWAY.Gateway
MangledTermError = ERRORS.MangledTermError
NoBackendError = ERRORS.NoBackendError


class FakeRouter:
    def __init__(self, answer=("alpha", "House"), raises=None):
        self.answer = answer
        self.raises = raises
        self.calls = 0
        self.protected = []

    async def translate(self, source, target, text, *, protected=()):
        self.calls += 1
        self.protected.append(tuple(protected))
        if self.raises:
            raise self.raises
        return self.answer


class FakeMemory:
    def __init__(self, reviewed=None, raises=None):
        self._reviewed = reviewed
        self.raises = raises

    def reviewed(self, target, text):
        if self.raises:
            raise self.raises
        return self._reviewed


class FakeGlossary:
    def __init__(self, terms=(), raises=None):
        self._terms = terms
        self.raises = raises

    def terms(self, target, text):
        if self.raises:
            raise self.raises
        return self._terms


def run(coro):
    return asyncio.run(coro)


class ReviewedStringWinsTestCase(unittest.TestCase):
    def test_a_reviewed_string_is_returned_and_no_engine_is_called(self) -> None:
        router = FakeRouter()
        gateway = Gateway(router, memory=FakeMemory("Haus (geprüft)"))

        self.assertEqual(
            run(gateway.translate("en", "de", "House")),
            ("weblate", "Haus (geprüft)"),
        )
        self.assertEqual(router.calls, 0, "no engine may be called")

    def test_without_a_reviewed_string_the_engines_answer(self) -> None:
        gateway = Gateway(FakeRouter(("alpha", "Haus")), memory=FakeMemory(None))

        self.assertEqual(run(gateway.translate("en", "de", "House")), ("alpha", "Haus"))

    def test_an_empty_reviewed_string_does_not_count_as_an_answer(self) -> None:
        gateway = Gateway(FakeRouter(("alpha", "Haus")), memory=FakeMemory(""))

        self.assertEqual(run(gateway.translate("en", "de", "House")), ("alpha", "Haus"))

    def test_a_memory_that_raises_falls_through_rather_than_failing(self) -> None:
        gateway = Gateway(
            FakeRouter(("alpha", "Haus")),
            memory=FakeMemory(raises=OSError("weblate is down")),
        )

        self.assertEqual(run(gateway.translate("en", "de", "House")), ("alpha", "Haus"))

    def test_without_weblate_the_router_answers(self) -> None:
        gateway = Gateway(FakeRouter(("alpha", "Haus")))

        self.assertEqual(run(gateway.translate("en", "de", "House")), ("alpha", "Haus"))


class GlossaryTestCase(unittest.TestCase):
    def test_the_protected_terms_travel_with_the_request(self) -> None:
        """They go to the router because that is what caches an answer."""
        router = FakeRouter(("alpha", "Infinito.Nexus ist gross"))
        gateway = Gateway(router, glossary=FakeGlossary(("Infinito.Nexus",)))

        engine, _answer = run(gateway.translate("en", "de", "Infinito.Nexus is big"))

        self.assertEqual(engine, "alpha")
        self.assertEqual(router.protected, [("Infinito.Nexus",)])

    def test_a_mangled_answer_reaches_the_caller_as_a_refusal(self) -> None:
        gateway = Gateway(
            FakeRouter(raises=MangledTermError("alpha dropped Infinito.Nexus")),
            glossary=FakeGlossary(("Infinito.Nexus",)),
        )

        with self.assertRaises(MangledTermError) as caught:
            run(gateway.translate("en", "de", "Infinito.Nexus is big"))

        self.assertIn("Infinito.Nexus", str(caught.exception))

    def test_a_glossary_that_raises_does_not_fail_the_request(self) -> None:
        gateway = Gateway(
            FakeRouter(("alpha", "Haus")), glossary=FakeGlossary(raises=OSError())
        )

        self.assertEqual(run(gateway.translate("en", "de", "House")), ("alpha", "Haus"))

    def test_the_reviewed_string_is_not_held_to_the_glossary(self) -> None:
        """A human reviewer outranks the term list as well as the engines."""
        gateway = Gateway(
            FakeRouter(),
            memory=FakeMemory("Unendlich ist gross"),
            glossary=FakeGlossary(("Infinito.Nexus",)),
        )

        self.assertEqual(
            run(gateway.translate("en", "de", "Infinito.Nexus is big")),
            ("weblate", "Unendlich ist gross"),
        )


class LoudFailureTestCase(unittest.TestCase):
    def test_a_router_failure_reaches_the_caller(self) -> None:
        gateway = Gateway(
            FakeRouter(raises=NoBackendError("every engine refused")),
            memory=FakeMemory(None),
        )

        with self.assertRaises(NoBackendError):
            run(gateway.translate("en", "de", "House"))


if __name__ == "__main__":
    unittest.main()
