"""Unit test: the gate and stack locks exclude a second holder and are read
without taking them, and the CI slot serves two concurrent requests for one
repository one after the other, in request order."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from utils.orchestrator import locks


class TestFlockLocks(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "locks"

    def test_a_free_lock_reads_as_free(self) -> None:
        self.assertFalse(locks.held(self.dir, locks.GATE))
        with locks.hold(self.dir, locks.GATE):
            pass
        self.assertFalse(locks.held(self.dir, locks.GATE))

    def test_a_held_lock_reads_as_held_and_excludes_a_second_holder(self) -> None:
        order: list[str] = []
        with locks.hold(self.dir, "stack-maintainer"):
            self.assertTrue(locks.held(self.dir, "stack-maintainer"))
            self.assertFalse(locks.held(self.dir, "stack-designer"))

            def second() -> None:
                with locks.hold(self.dir, "stack-maintainer"):
                    order.append("second")

            thread = threading.Thread(target=second)
            thread.start()
            thread.join(0.3)
            self.assertTrue(thread.is_alive())
            order.append("first")
        thread.join(5)
        self.assertEqual(order, ["first", "second"])

    def test_wait_gate_returns_only_after_the_gate_is_released(self) -> None:
        released = threading.Event()
        held = threading.Event()

        def gate() -> None:
            with locks.hold(self.dir, locks.GATE):
                held.set()
                released.wait(5)

        thread = threading.Thread(target=gate)
        thread.start()
        held.wait(5)
        polls: list[float] = []

        def sleep(seconds: float) -> None:
            polls.append(seconds)
            released.set()
            thread.join(5)

        locks.wait_gate(self.dir, poll=2.0, sleep=sleep)
        self.assertEqual(polls, [2.0])
        self.assertFalse(locks.held(self.dir, locks.GATE))

    def test_a_lock_name_cannot_leave_the_lock_directory(self) -> None:
        for name in ("../gate", "Gate", "stack/x", "", "gate\n"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                locks.lock_file(self.dir, name)


class TestSlotQueue(unittest.TestCase):
    def test_two_concurrent_requests_are_served_in_turn(self) -> None:
        slots = locks.SlotQueue()
        barrier = threading.Barrier(2)
        places: dict[str, int] = {}

        def ask(agent: str) -> None:
            barrier.wait(5)
            places[agent] = slots.request("infinito-nexus/core", agent)

        threads = [
            threading.Thread(target=ask, args=(agent,))
            for agent in ("mant0alice", "impl0bob")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(sorted(places.values()), [0, 1])
        first = min(places, key=places.__getitem__)
        second = max(places, key=places.__getitem__)
        self.assertEqual(slots.request("infinito-nexus/core", second), 1)
        self.assertEqual(slots.release("infinito-nexus/core", first), second)
        self.assertEqual(slots.request("infinito-nexus/core", second), 0)
        self.assertIsNone(slots.release("infinito-nexus/core", second))

    def test_another_repository_has_its_own_slot(self) -> None:
        slots = locks.SlotQueue()
        self.assertEqual(slots.request("infinito-nexus/core", "mant0alice"), 0)
        self.assertEqual(slots.request("infinito-nexus/gui", "impl0bob"), 0)


if __name__ == "__main__":
    unittest.main()
