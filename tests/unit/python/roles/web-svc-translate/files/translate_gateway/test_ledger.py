"""A store that cannot answer leaves the request standing, and says so."""

from __future__ import annotations

import asyncio
import unittest

from . import LEDGER

Ledger = LEDGER.Ledger


def run(coro):
    return asyncio.run(coro)


def ledger(**stores):
    return Ledger(
        history=stores.get("history"),
        cache=stores.get("cache"),
        failures=stores.get("failures"),
        rejections=stores.get("rejections"),
    )


class Down:
    def __getattr__(self, _name):
        async def refuse(*args):
            raise ConnectionError(f"server closed while sending {args!r}")

        return refuse


class Recording:
    def __init__(self):
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        async def record(*args):
            self.calls.append((name, *args))

        return record


class NoStoreTestCase(unittest.TestCase):
    def test_every_read_without_a_store_is_empty(self) -> None:
        empty = ledger()

        self.assertEqual(run(empty.tally("c")), {})
        self.assertEqual(run(empty.speeds("c")), {})
        self.assertEqual(run(empty.streaks()), {})
        self.assertEqual(run(empty.failure_totals()), {})
        self.assertEqual(run(empty.rejection_counts("en", "de")), {})
        self.assertIsNone(run(empty.cached("a", "en", "de", "x", "text", ())))


class AStoreThatIsDownTestCase(unittest.TestCase):
    def test_a_read_falls_back_and_logs_the_class_only(self) -> None:
        down = ledger(history=Down(), cache=Down())

        with self.assertLogs(LEDGER.LOGGER, level="WARNING") as logged:
            self.assertEqual(run(down.tally("secret text")), {})
            self.assertIsNone(
                run(down.cached("a", "en", "de", "secret text", "text", ()))
            )

        output = "\n".join(logged.output)
        self.assertIn("the learning log could not be read", output)
        self.assertIn("the cache could not be read", output)
        self.assertIn("ConnectionError", output)
        self.assertNotIn("secret text", output)

    def test_a_write_is_dropped_and_logs_the_class_only(self) -> None:
        down = ledger(cache=Down(), failures=Down(), rejections=Down())

        with self.assertLogs(LEDGER.LOGGER, level="WARNING") as logged:
            run(down.store("a", "en", "de", "secret text", "answer", "text", ()))
            run(down.failed("a"))
            run(down.rejected("a", "en", "de"))

        output = "\n".join(logged.output)
        for store in ("cache", "failure log", "rejection log"):
            with self.subTest(store=store):
                self.assertIn(f"the {store} could not be written", output)
        self.assertNotIn("secret text", output)


class TheSpansReachTheCacheTestCase(unittest.TestCase):
    def test_both_directions_pass_the_protected_spans(self) -> None:
        cache = Recording()
        both = ledger(cache=cache)

        run(both.cached("a", "en", "de", "x", "text", ("Nextcloud",)))
        run(both.store("a", "en", "de", "x", "y", "text", ("Nextcloud",)))

        self.assertEqual(
            cache.calls,
            [
                ("get", "a", "en", "de", "x", "text", ("Nextcloud",)),
                ("set", "a", "en", "de", "x", "y", "text", ("Nextcloud",)),
            ],
        )


if __name__ == "__main__":
    unittest.main()
