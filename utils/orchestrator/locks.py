"""The machine locks the orchestrator, the agents and the quality gate share.

The gate lock and one stack lock per agent are ``flock`` files in one lock
directory, so a shell (``flock <dir>/gate.lock make quality``) and the
orchestrator see the same state. The CI slot is a first-come queue per
repository: two agents asking for a CI deploy of the same repository get it
one after the other, in the order they asked.
"""

from __future__ import annotations

import fcntl
import re
import threading
from collections import deque
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

GATE = "gate"
STACK_PREFIX = "stack-"
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def lock_file(directory: Path, name: str) -> Path:
    """Return the lock file of ``name`` under ``directory``.

    Args:
        directory: the machine's lock directory.
        name: ``gate`` or ``stack-<agent>``.

    Raises:
        ValueError: ``name`` is not a plain lowercase name.
    """
    if not _NAME.fullmatch(name):
        raise ValueError(f"lock name {name!r} is not a plain lowercase name")
    return directory / f"{name}.lock"


def stack_file(directory: Path, agent: str) -> Path:
    """Return ``agent``'s stack lock file: every stack command of the agent
    runs under it, so two of them never overlap.

    Args:
        directory: the machine's lock directory.
        agent: the agent role or account name.
    """
    return lock_file(directory, f"{STACK_PREFIX}{agent}")


@contextmanager
def hold(directory: Path, name: str) -> Iterator[None]:
    """Hold the exclusive lock ``name`` for the block, waiting until it is free.

    Args:
        directory: the machine's lock directory; created when missing.
        name: ``gate`` or ``stack-<agent>``.
    """
    path = lock_file(directory, name)
    directory.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def held(directory: Path, name: str) -> bool:
    """Return whether a holder has the lock ``name`` right now.

    Args:
        directory: the machine's lock directory.
        name: ``gate`` or ``stack-<agent>``.
    """
    path = lock_file(directory, name)
    if not path.is_file():
        return False
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


def wait_gate(directory: Path, *, poll: float, sleep: Callable[[float], None]) -> None:
    """Return once the gate lock is free.

    Args:
        directory: the machine's lock directory.
        poll: seconds between two reads of the gate lock.
        sleep: the wait between two reads.
    """
    while held(directory, GATE):
        sleep(poll)


class SlotQueue:
    """One CI deploy slot per repository, granted in request order."""

    def __init__(self) -> None:
        self._queues: dict[str, deque[str]] = {}
        self._lock = threading.Lock()

    def request(self, repository: str, agent: str) -> int:
        """Queue ``agent`` for ``repository``'s slot and return its place; 0
        holds the slot. A repeated request keeps the earlier place.

        Args:
            repository: the ``owner/name`` of the repository.
            agent: the agent account name.
        """
        with self._lock:
            queue = self._queues.setdefault(repository, deque())
            if agent not in queue:
                queue.append(agent)
            return queue.index(agent)

    def release(self, repository: str, agent: str) -> str | None:
        """Give up ``agent``'s slot or place and return the next holder.

        Args:
            repository: the ``owner/name`` of the repository.
            agent: the agent account name.
        """
        with self._lock:
            queue = self._queues.get(repository, deque())
            if agent in queue:
                queue.remove(agent)
            return queue[0] if queue else None
