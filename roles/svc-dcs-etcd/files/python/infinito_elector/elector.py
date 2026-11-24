"""The election loop that ties one lock to one role backend."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from . import LEASE_SECONDS, RENEW_DEADLINE_SECONDS, RETRY_SECONDS
from .lock import LockError
from .roles import RoleError, choose

if TYPE_CHECKING:
    from collections.abc import Callable

    from .lock import Lock
    from .roles import Role

LOG = logging.getLogger("infinito_elector")
YIELD_TICKS = 3


class FatalError(Exception):
    """The instance could not be made read-only.

    The process exits on it, which stops the engine next to it: an instance
    that may still accept writes must not keep running unsupervised.
    """


class Elector:
    """Keep the local instance writable exactly while it holds the lease.

    Args:
        lock: the lease backend.
        role: the engine backend.
        host_id: this instance's host id, also the lease's identity.
        clock: monotonic seconds; injected so tests drive time.
        lease_seconds: lease TTL; MUST exceed *renew_deadline*.
        renew_deadline: seconds after the last successful renew at which the
            instance stops writing, whatever the store says.
        retry_seconds: pause between two ticks.
    """

    def __init__(
        self,
        lock: Lock,
        role: Role,
        host_id: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        lease_seconds: float = LEASE_SECONDS,
        renew_deadline: float = RENEW_DEADLINE_SECONDS,
        retry_seconds: float = RETRY_SECONDS,
    ) -> None:
        if renew_deadline >= lease_seconds:
            raise ValueError("renew deadline must be shorter than the lease")
        self.lock = lock
        self.role = role
        self.host_id = host_id
        self.clock = clock
        self.lease_seconds = lease_seconds
        self.renew_deadline = renew_deadline
        self.retry_seconds = retry_seconds
        self.holding = False
        self.renewed_at = float("-inf")
        self.writable_seen = False
        self._yield_until = float("-inf")
        self._mutex = threading.RLock()

    def _within_deadline(self) -> bool:
        return self.clock() - self.renewed_at < self.renew_deadline

    def _observe_writable(self) -> None:
        try:
            self.writable_seen = self.role.is_writable()
        except RoleError:
            self.writable_seen = False

    def serving_writer(self) -> bool:
        """What ``GET /writer`` answers: holding the lease, inside the renew
        deadline, and the engine writable as of the last tick.

        Reads state the loop keeps instead of querying the engine: health
        checks queued behind a slow tick would otherwise all open engine
        connections at once and exhaust the engine's connection limit.
        """
        return self.holding and self.writable_seen and self._within_deadline()

    def step_down(self) -> None:
        """Read-only first, then release.

        Raises:
            FatalError: the engine refused to turn read-only. The lease is
                kept on purpose then: releasing it would let a second writer
                start next to one that may still be writing.
        """
        with self._mutex:
            self.writable_seen = False
            try:
                self.role.become_read_only()
            except RoleError as error:
                self.holding = False
                raise FatalError(f"could not turn read-only: {error}") from error
            was_holding, self.holding = self.holding, False
            if was_holding:
                try:
                    self.lock.release()
                except LockError as error:
                    LOG.warning("release failed, lease expires on its own: %s", error)

    def tick(self) -> None:
        """One round of the loop."""
        with self._mutex:
            if self.holding:
                self._renew()
            else:
                self._compete()

    def _renew(self) -> None:
        started = self.clock()
        try:
            renewed = self.lock.renew()
        except LockError as error:
            LOG.warning("renew failed: %s", error)
            renewed = None
        if renewed:
            self.renewed_at = started
            self._observe_writable()
            return
        if renewed is False or not self._within_deadline():
            LOG.warning("lost the writer lease, turning read-only")
            self.step_down()

    def _ensure_read_only(self) -> None:
        try:
            writable = self.role.is_writable()
        except RoleError:
            writable = True
        if writable:
            try:
                self.role.become_read_only()
            except RoleError as error:
                raise FatalError(f"could not turn read-only: {error}") from error

    def _compete(self) -> None:
        self._ensure_read_only()
        try:
            holder = self.lock.holder()
        except LockError as error:
            LOG.warning("coordination store unreachable: %s", error)
            return
        if holder is not None:
            if holder != self.host_id:
                try:
                    self.role.follow(holder)
                except RoleError as error:
                    LOG.warning("cannot follow %s: %s", holder, error)
                    return
                self.role.watch()
            return
        if self.clock() < self._yield_until or not self.role.is_ready_to_compete():
            return
        started = self.clock()
        try:
            if not self.lock.acquire():
                return
        except LockError as error:
            LOG.warning("acquire failed: %s", error)
            return
        self.holding = True
        self.renewed_at = started
        try:
            ranks = {self.host_id: self.role.rank(), **self.role.peer_ranks()}
        except RoleError as error:
            LOG.warning("cannot rank this instance: %s", error)
            self.step_down()
            return
        if len(ranks) < self.role.quorum():
            LOG.warning(
                "ranked %d of the %d instances a promotion needs, leaving the lease",
                len(ranks),
                self.role.quorum(),
            )
            self.step_down()
            return
        best = choose(ranks)
        if best != self.host_id:
            LOG.info("%s is further ahead, leaving the lease to it", best)
            self.step_down()
            self._yield_until = self.clock() + YIELD_TICKS * self.retry_seconds
            return
        try:
            self.role.become_writer()
        except RoleError as error:
            LOG.warning("promotion failed: %s", error)
            self.step_down()
            return
        if not self._within_deadline():
            LOG.warning("promotion outlived the renew deadline")
            self.step_down()
            return
        self._observe_writable()
        LOG.info("%s is the writer, ranked %s", self.host_id, ranks)

    def run(
        self,
        stop: threading.Event,
        wait: Callable[[float], object] | None = None,
    ) -> None:
        """Tick until *stop* is set, then step down.

        Args:
            stop: set by the SIGTERM handler.
            wait: pause between ticks; defaults to ``stop.wait`` so a signal
                ends the pause at once.
        """
        pause = wait or stop.wait
        try:
            while not stop.is_set():
                self.tick()
                pause(self.retry_seconds)
        finally:
            self.step_down()
