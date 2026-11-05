from __future__ import annotations

import threading
import unittest

from infinito_elector_src.elector import Elector, FatalError
from infinito_elector_src.lock import Lock, LockError
from infinito_elector_src.roles import ReseedRequired, Role, RoleError

from . import _NAME  # noqa: F401  side-effect import registers infinito_elector_src


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Store:
    """One shared key with a TTL lease, on the fake clock."""

    def __init__(self, clock: Clock, ttl: float = 15) -> None:
        self.clock = clock
        self.ttl = ttl
        self.holder: str | None = None
        self.expires = 0.0

    def current(self) -> str | None:
        if self.holder is not None and self.clock() >= self.expires:
            self.holder = None
        return self.holder


class FakeLock(Lock):
    def __init__(self, store: Store, identity: str, journal: list) -> None:
        self.store = store
        self.identity = identity
        self.journal = journal
        self.partitioned = False

    def _check(self) -> None:
        if self.partitioned:
            raise LockError("partitioned")

    def acquire(self) -> bool:
        self._check()
        if self.store.current() is None:
            self.store.holder = self.identity
            self.store.expires = self.store.clock() + self.store.ttl
            return True
        return False

    def renew(self) -> bool:
        self._check()
        if self.store.current() != self.identity:
            return False
        self.store.expires = self.store.clock() + self.store.ttl
        return True

    def release(self) -> None:
        self.journal.append(("release", self.identity))
        self._check()
        if self.store.current() == self.identity:
            self.store.holder = None

    def holder(self) -> str | None:
        self._check()
        return self.store.current()


class FakeRole(Role):
    def __init__(self, host: str, rank: int, journal: list, peers=None) -> None:
        self.host = host
        self._rank = rank
        self.journal = journal
        self.writable = False
        self.ready = True
        self.peers: dict[str, int] = peers or {}
        self.followed: str | None = None
        self.fail_read_only = False

    def is_ready_to_compete(self) -> bool:
        return self.ready

    def become_writer(self) -> None:
        self.journal.append(("writer", self.host))
        self.writable = True

    def become_read_only(self) -> None:
        self.journal.append(("read_only", self.host))
        if self.fail_read_only:
            raise RoleError("refused")
        self.writable = False

    def is_writable(self) -> bool:
        return self.writable

    def rank(self) -> int:
        return self._rank

    def peer_ranks(self) -> dict[str, int]:
        return dict(self.peers)

    def follow(self, writer: str | None) -> None:
        self.followed = writer


def _pair():
    clock = Clock()
    store = Store(clock)
    journal: list = []
    electors = []
    for host in ("a", "b"):
        role = FakeRole(host, 0, journal)
        electors.append(
            Elector(FakeLock(store, host, journal), role, host, clock=clock)
        )
    return clock, store, journal, electors


class TestElection(unittest.TestCase):
    def test_first_ready_instance_becomes_writer(self) -> None:
        _, _, _, (a, b) = _pair()
        a.tick()
        b.tick()
        self.assertTrue(a.serving_writer())
        self.assertFalse(b.serving_writer())
        self.assertEqual(b.role.followed, "a")

    def test_an_instance_that_yields_leaves_the_lease_to_the_better_peer(self) -> None:
        _clock, _, _, (a, b) = _pair()
        a.role.peers = {"b": 5}
        b.role._rank = 5
        a.tick()
        self.assertFalse(a.holding)
        a.tick()
        self.assertFalse(a.holding)
        b.tick()
        self.assertTrue(b.serving_writer())

    def test_no_promotion_without_a_ranked_majority(self) -> None:
        _, _, journal, (a, _) = _pair()
        a.role.quorum = lambda: 2
        a.tick()
        self.assertNotIn(("writer", "a"), journal)
        self.assertFalse(a.holding)

    def test_not_ready_instance_does_not_compete(self) -> None:
        _, _, _, (a, _) = _pair()
        a.role.ready = False
        a.tick()
        self.assertFalse(a.holding)

    def test_never_two_writers_when_the_holder_is_partitioned(self) -> None:
        clock, _, _, (a, b) = _pair()
        a.tick()
        a.lock.partitioned = True
        while clock.now < 60:
            clock.now += 0.5
            if clock.now % 2 == 0:
                a.tick()
                b.tick()
            writers = [e for e in (a, b) if e.role.is_writable()]
            self.assertLessEqual(len(writers), 1, clock.now)
            serving = [e for e in (a, b) if e.serving_writer()]
            self.assertLessEqual(len(serving), 1, clock.now)
        self.assertTrue(b.serving_writer())
        self.assertFalse(a.role.is_writable())

    def test_stops_serving_at_the_renew_deadline_even_between_ticks(self) -> None:
        clock, _, _, (a, _) = _pair()
        a.tick()
        a.lock.partitioned = True
        clock.now = 9.9
        self.assertTrue(a.serving_writer())
        clock.now = 10
        self.assertFalse(a.serving_writer())

    def test_serving_writer_never_queries_the_engine(self) -> None:
        _, _, _, (a, _) = _pair()
        a.tick()
        calls = []
        real = a.role.is_writable
        a.role.is_writable = lambda: calls.append(1) or real()
        for _ in range(50):
            self.assertTrue(a.serving_writer())
        self.assertEqual(calls, [])

    def test_serving_writer_answers_while_a_tick_holds_the_lock(self) -> None:
        _, _, _, (a, _) = _pair()
        a.tick()
        answers: list[bool] = []
        with a._mutex:
            reader = threading.Thread(target=lambda: answers.append(a.serving_writer()))
            reader.start()
            reader.join(timeout=2)
        self.assertEqual(answers, [True])

    def test_an_engine_turned_read_only_stops_serving_after_the_next_tick(self) -> None:
        clock, _, _, (a, _) = _pair()
        a.tick()
        a.role.writable = False
        clock.now = 2
        a.tick()
        self.assertFalse(a.serving_writer())

    def test_fails_closed_when_etcd_is_lost(self) -> None:
        clock, _, _, (a, _) = _pair()
        a.tick()
        a.lock.partitioned = True
        clock.now = 2
        a.tick()
        self.assertTrue(a.role.is_writable())
        clock.now = 10
        a.tick()
        self.assertFalse(a.role.is_writable())
        self.assertFalse(a.holding)

    def test_read_only_before_release_on_lost_lease(self) -> None:
        clock, store, journal, (a, _) = _pair()
        a.tick()
        store.holder = "someone-else"
        clock.now = 2
        a.tick()
        events = [event for event in journal if event[1] == "a"]
        self.assertLess(
            events.index(("read_only", "a")), events.index(("release", "a"))
        )

    def test_sigterm_turns_read_only_then_releases(self) -> None:
        _, store, journal, (a, b) = _pair()
        stop = threading.Event()

        def pause(_seconds: float) -> None:
            stop.set()

        a.run(stop, pause)
        self.assertFalse(a.role.is_writable())
        self.assertIsNone(store.current())
        tail = [event for event in journal if event[1] == "a"][-2:]
        self.assertEqual(tail, [("read_only", "a"), ("release", "a")])
        b.tick()
        self.assertTrue(b.serving_writer())

    def test_refused_read_only_keeps_the_lease_and_is_fatal(self) -> None:
        _, store, journal, (a, _) = _pair()
        a.tick()
        a.role.fail_read_only = True
        with self.assertRaises(FatalError):
            a.step_down()
        self.assertNotIn(("release", "a"), journal)
        self.assertEqual(store.current(), "a")

    def test_a_writable_loser_is_forced_read_only(self) -> None:
        _, _, _, (a, b) = _pair()
        a.tick()
        b.role.writable = True
        b.tick()
        self.assertFalse(b.role.is_writable())

    def test_lagging_instance_leaves_the_lease_to_the_most_advanced(self) -> None:
        clock = Clock()
        store = Store(clock)
        journal: list = []
        lagging = Elector(
            FakeLock(store, "a", journal),
            FakeRole("a", 5, journal, peers={"b": 9}),
            "a",
            clock=clock,
        )
        ahead = Elector(
            FakeLock(store, "b", journal),
            FakeRole("b", 9, journal, peers={"a": 5}),
            "b",
            clock=clock,
        )
        lagging.tick()
        self.assertFalse(lagging.holding)
        self.assertNotIn(("writer", "a"), journal)
        ahead.tick()
        self.assertTrue(ahead.serving_writer())

    def test_a_follower_is_watched_after_it_follows(self) -> None:
        _, _, _, (a, b) = _pair()
        a.tick()
        b.role.watch = lambda: (_ for _ in ()).throw(ReseedRequired("diverged"))
        with self.assertRaises(ReseedRequired):
            b.tick()
        self.assertEqual(b.role.followed, "a")

    def test_rejects_a_deadline_that_outlives_the_lease(self) -> None:
        clock = Clock()
        with self.assertRaises(ValueError):
            Elector(
                FakeLock(Store(clock), "a", []),
                FakeRole("a", 0, []),
                "a",
                clock=clock,
                lease_seconds=10,
                renew_deadline=10,
            )


if __name__ == "__main__":
    unittest.main()
