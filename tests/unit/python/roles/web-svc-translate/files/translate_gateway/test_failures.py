"""Failing is not losing: an engine's errors are counted on their own."""

from __future__ import annotations

import asyncio
import unittest
from typing import ClassVar

from . import FAILURES

FailureLog = FAILURES.FailureLog


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
    REJECTED: ClassVar[list[str]] = ["", "Failures", "a-b", "drop table x; --"]

    def test_a_bare_lowercase_identifier_is_accepted(self) -> None:
        self.assertIsNotNone(FailureLog(FakeClient(), "translate_failures"))

    def test_anything_else_is_refused(self) -> None:
        for name in self.REJECTED:
            with self.subTest(name=name), self.assertRaises(ValueError):
                FailureLog(FakeClient(), name)


class CountingTestCase(unittest.TestCase):
    def test_a_failure_lengthens_the_streak_and_the_total(self) -> None:
        client = FakeClient()
        run(FailureLog(client, "translate_failures").failed("alpha"))

        statement, params = client.executed[-1]
        self.assertIn("INSERT INTO translate_failures", statement)
        self.assertIn("streak = translate_failures.streak + 1", statement)
        self.assertIn("total = translate_failures.total + 1", statement)
        self.assertEqual(params, ("alpha",))

    def test_an_answer_clears_the_streak_but_keeps_the_total(self) -> None:
        client = FakeClient()
        run(FailureLog(client, "translate_failures").cleared("alpha"))

        statement, params = client.executed[-1]
        self.assertIn("SET streak = 0", statement)
        self.assertNotIn("total", statement.split("SET", 1)[1])
        self.assertEqual(params, ("alpha",))

    def test_streaks_reads_only_engines_that_are_failing(self) -> None:
        client = FakeClient(rows=[{"engine": "alpha", "streak": 4}])

        self.assertEqual(
            run(FailureLog(client, "translate_failures").streaks()), {"alpha": 4}
        )
        self.assertIn("WHERE streak > 0", client.executed[-1][0])

    def test_the_table_is_created_once(self) -> None:
        client = FakeClient(rows=[])
        log = FailureLog(client, "translate_failures")

        run(log.streaks())
        run(log.streaks())

        created = [
            statement
            for statement, _params in client.executed
            if statement.startswith("CREATE TABLE")
        ]
        self.assertEqual(len(created), 1)


if __name__ == "__main__":
    unittest.main()
