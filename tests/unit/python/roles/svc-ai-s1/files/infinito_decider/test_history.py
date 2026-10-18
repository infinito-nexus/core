"""The learning log writes one row per offered option and reads back the tally."""

from __future__ import annotations

import asyncio
import unittest
from typing import ClassVar

from . import HISTORY

History = HISTORY.History
record_of = HISTORY.record_of


class FakeClient:
    """Records the statements a History issues and answers its one query."""

    def __init__(self, rows=None):
        self.executed: list[tuple] = []
        self.queried: list[tuple] = []
        self._rows = rows or []

    async def execute_raw(self, statement, *params):
        self.executed.append((statement, params))

    async def query_raw(self, statement, *params):
        self.queried.append((statement, params))
        return self._rows


class TableNameTestCase(unittest.TestCase):
    REJECTED: ClassVar[list[str]] = [
        "",
        "Router_History",
        "router history",
        "router-history",
        "drop table x; --",
        "1router",
    ]

    def test_a_bare_lowercase_identifier_is_accepted(self) -> None:
        self.assertIsNotNone(History(FakeClient(), "infinito_router_history"))

    def test_anything_else_is_refused_before_a_statement_is_built(self) -> None:
        for name in self.REJECTED:
            with self.subTest(name=name), self.assertRaises(ValueError):
                History(FakeClient(), name)

    def test_the_ddl_and_index_carry_the_table(self) -> None:
        history = History(FakeClient(), "infinito_router_history")

        self.assertIn("infinito_router_history (", history.ddl)
        self.assertIn("infinito_router_history_signature_idx", history.index)


class RecordTestCase(unittest.TestCase):
    def test_it_creates_the_table_once_and_writes_one_row_per_option(self) -> None:
        client = FakeClient()
        history = History(client, "log")

        asyncio.run(history.record("de:en:short", "alpha", ["alpha", "beta"]))
        asyncio.run(history.record("de:en:short", "beta", ["alpha", "beta"]))

        creates = [s for s, _ in client.executed if s.startswith("CREATE")]
        inserts = [(s, p) for s, p in client.executed if s.startswith("INSERT")]
        self.assertEqual(len(creates), 2, "DDL and index run once, not per record")
        self.assertEqual(len(inserts), 4)
        self.assertEqual([p[2] for _, p in inserts], [True, False, False, True])

    def test_the_signature_and_alias_travel_as_parameters(self) -> None:
        client = FakeClient()

        asyncio.run(History(client, "log").record("sig", "alpha", ["alpha"]))

        statement, params = next(
            (s, p) for s, p in client.executed if s.startswith("INSERT")
        )
        self.assertIn("VALUES ($1, $2, $3)", statement)
        self.assertEqual(params, ("sig", "alpha", True))


class WinsTestCase(unittest.TestCase):
    def test_it_folds_the_rows_into_won_and_seen(self) -> None:
        client = FakeClient([{"alias": "alpha", "won": 2, "seen": 5}])

        tally = asyncio.run(History(client, "log").wins("sig"))

        self.assertEqual(tally, {"alpha": (2, 5)})

    def test_an_untried_class_reads_as_empty(self) -> None:
        self.assertEqual(asyncio.run(History(FakeClient([]), "log").wins("sig")), {})

    def test_a_client_answering_none_reads_as_empty(self) -> None:
        self.assertEqual(asyncio.run(History(FakeClient(None), "log").wins("sig")), {})


class RecordOfTestCase(unittest.TestCase):
    def test_a_known_option_gets_a_clause(self) -> None:
        self.assertEqual(
            record_of("alpha", {"alpha": (2, 5)}), "won 2 of 5 comparisons like this"
        )

    def test_an_unknown_option_gets_nothing(self) -> None:
        self.assertEqual(record_of("beta", {"alpha": (2, 5)}), "")

    def test_an_option_seen_zero_times_gets_nothing(self) -> None:
        self.assertEqual(record_of("alpha", {"alpha": (0, 0)}), "")


if __name__ == "__main__":
    unittest.main()
