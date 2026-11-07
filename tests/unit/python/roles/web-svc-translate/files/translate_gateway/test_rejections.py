"""A rejected answer is counted per engine and language pair, on its own."""

from __future__ import annotations

import asyncio
import unittest

from . import REJECTIONS

RejectionLog = REJECTIONS.RejectionLog
pair_of = REJECTIONS.pair_of


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


class PairTestCase(unittest.TestCase):
    def test_a_declared_pair_keeps_both_codes(self) -> None:
        self.assertEqual(pair_of("en", "de"), "en:de")

    def test_an_undeclared_source_reads_as_auto(self) -> None:
        self.assertEqual(pair_of(None, "de"), "auto:de")


class CountingTestCase(unittest.TestCase):
    def test_a_rejection_adds_one_to_the_engines_count_for_the_pair(self) -> None:
        client = FakeClient()
        run(RejectionLog(client).rejected("alpha", "en", "de"))

        statement, params = client.executed[-1]
        self.assertIn("INSERT INTO infinito_translate_rejections", statement)
        self.assertIn("ON CONFLICT (engine, pair)", statement)
        self.assertIn("total = infinito_translate_rejections.total + 1", statement)
        self.assertEqual(params, ("alpha", "en:de"))

    def test_counts_are_read_for_one_pair_only(self) -> None:
        """A pair an engine mangles must not cost it standing on another."""
        client = FakeClient(rows=[{"engine": "alpha", "total": 3}])

        self.assertEqual(run(RejectionLog(client).counts("en", "de")), {"alpha": 3})
        statement, params = client.executed[-1]
        self.assertIn("WHERE pair = $1", statement)
        self.assertEqual(params, ("en:de",))

    def test_an_empty_log_counts_nothing(self) -> None:
        self.assertEqual(
            run(RejectionLog(FakeClient(rows=None)).counts("en", "de")), {}
        )

    def test_the_pair_travels_as_a_parameter_not_in_the_statement(self) -> None:
        client = FakeClient(rows=[])
        run(RejectionLog(client).counts("en", "de"))

        self.assertNotIn("en:de", client.executed[-1][0])

    def test_the_table_is_created_once(self) -> None:
        client = FakeClient(rows=[])
        log = RejectionLog(client)

        run(log.counts("en", "de"))
        run(log.rejected("alpha", "en", "de"))

        created = [
            statement
            for statement, _params in client.executed
            if statement.startswith("CREATE TABLE")
        ]
        self.assertEqual(len(created), 1)

    def test_the_table_is_keyed_on_engine_and_pair(self) -> None:
        self.assertIn("PRIMARY KEY (engine, pair)", REJECTIONS.DDL)


if __name__ == "__main__":
    unittest.main()
