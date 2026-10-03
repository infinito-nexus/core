"""A translation already paid for is not bought twice."""

from __future__ import annotations

import asyncio
import unittest
from typing import ClassVar

from . import CACHE

TranslationCache = CACHE.TranslationCache


class FakeClient:
    def __init__(self, rows=None):
        self.executed: list[tuple] = []
        self._rows = rows

    async def execute_raw(self, statement, *params):
        self.executed.append((statement, params))

    async def query_raw(self, statement, *params):
        self.executed.append((statement, params))
        return self._rows


def run(coro):
    return asyncio.run(coro)


class TableNameTestCase(unittest.TestCase):
    REJECTED: ClassVar[list[str]] = ["", "Cache", "a-b", "drop table x; --", "1cache"]

    def test_a_bare_lowercase_identifier_is_accepted(self) -> None:
        self.assertIsNotNone(TranslationCache(FakeClient(), "translation_cache"))

    def test_anything_else_is_refused(self) -> None:
        for name in self.REJECTED:
            with self.subTest(name=name), self.assertRaises(ValueError):
                TranslationCache(FakeClient(), name)


class ReadTestCase(unittest.TestCase):
    def test_a_stored_answer_comes_back(self) -> None:
        cache = TranslationCache(FakeClient([{"translation": "Haus"}]), "c")

        self.assertEqual(run(cache.get("alpha", "en", "de", "House")), "Haus")

    def test_an_unknown_request_reads_as_none(self) -> None:
        self.assertIsNone(
            run(TranslationCache(FakeClient([]), "c").get("a", "e", "d", "x"))
        )

    def test_a_client_answering_none_reads_as_none(self) -> None:
        self.assertIsNone(
            run(TranslationCache(FakeClient(None), "c").get("a", "e", "d", "x"))
        )

    def test_the_table_is_created_once_not_per_read(self) -> None:
        client = FakeClient([])
        cache = TranslationCache(client, "c")

        run(cache.get("alpha", "en", "de", "House"))
        run(cache.get("alpha", "en", "de", "Hof"))

        creates = [s for s, _ in client.executed if s.startswith("CREATE")]
        self.assertEqual(len(creates), 1)


class WriteTestCase(unittest.TestCase):
    def test_the_key_travels_as_a_parameter_not_in_the_statement(self) -> None:
        client = FakeClient()

        run(TranslationCache(client, "c").set("alpha", "en", "de", "House", "Haus"))

        statement, params = client.executed[-1]
        self.assertIn("VALUES ($1, $2)", statement)
        self.assertEqual(params[1], "Haus")
        self.assertNotIn("House", statement)

    def test_a_second_answer_for_one_key_replaces_the_first(self) -> None:
        client = FakeClient()

        run(TranslationCache(client, "c").set("alpha", "en", "de", "House", "Haus"))

        statement, _params = client.executed[-1]
        self.assertIn("ON CONFLICT (key) DO UPDATE", statement)

    def test_two_engines_write_two_keys(self) -> None:
        client = FakeClient()
        cache = TranslationCache(client, "c")

        run(cache.set("alpha", "en", "de", "House", "Haus"))
        run(cache.set("beta", "en", "de", "House", "Gebaeude"))

        keys = [p[0] for s, p in client.executed if s.startswith("INSERT")]
        self.assertEqual(len(set(keys)), 2)


if __name__ == "__main__":
    unittest.main()
