"""Unit test: the store takes only a plain lowercase PostgreSQL identifier as
its table name, because the name is spliced into every statement it runs."""

from __future__ import annotations

import sys
import types
import unittest
import unittest.mock as mock

from . import load

with mock.patch.dict(sys.modules, {"asyncpg": types.ModuleType("asyncpg")}):
    store = load("store")

DSN = "postgresql://assistant@db/assistant"


class TestTableName(unittest.TestCase):
    def test_the_configured_name_is_accepted(self) -> None:
        self.assertEqual(
            "assistant_passages", store.Store(DSN, "assistant_passages")._table
        )

    def test_a_name_outside_a_plain_identifier_is_refused(self) -> None:
        for table in (
            "x; DROP TABLE users",
            "x--",
            'x"',
            "Passages",
            "ünicode",
            "1x",
            "",
            "a" * 64,
        ):
            with self.subTest(table=table), self.assertRaises(ValueError):
                store.Store(DSN, table)


if __name__ == "__main__":
    unittest.main()
