"""The orchestrator's scheduler tick and routine runner, the stack-free part.

``tick`` folds one minute of the deployed cron entries into one action per
routine: it asks ``cron.due`` which entries fire under the gate lock, the
owner holds, the blockers and the measured load, and lets a pause outrank a
start of the same routine. ``Runner`` starts a routine of the deployed
revision as a child process, one run per routine at a time, after the gate
lock is free, stops a live run's process group where it stands on a
``pause`` and continues it on the next ``start``; the process spawn, the
signal and the gate wait are injected so a fixture clock and a fixture lock
drive it.
"""

from __future__ import annotations

import signal
import threading
from typing import TYPE_CHECKING, Protocol

from utils.orchestrator.cron import due
from utils.orchestrator.load import PAUSE, START, conditions, lane_action
from utils.orchestrator.locks import stack_file

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from utils.orchestrator.load import Load

ROUTINE_COMMAND = ("python3", "-m", "agents.routines", "run")
STARTED = "started"
RUNNING = "running"
RESUMED = "resumed"
PAUSED = "paused"
IDLE = "idle"


class Process(Protocol):
    pid: int

    def poll(self) -> int | None: ...


def tick(
    entries: list[dict],
    now: datetime,
    *,
    sample: tuple[Load, Load] | None,
    accelerated: bool,
    gate_locked: bool,
    held: frozenset[str],
    blocked: frozenset[str],
) -> dict[str, str]:
    """Return the action (``start`` or ``pause``) per routine for ``now``.

    Args:
        entries: the deployed cron entries of every agent role.
        now: the current UTC minute.
        sample: the host and the translation lane load measured at this tick,
            or ``None`` when nothing was measured, so no load condition holds.
        accelerated: whether the host hands a GPU to the lane.
        gate_locked: whether the machine's gate lock is held.
        held: the routines the owner has put on hold.
        blocked: the routines with a recorded owner-only blocker.
    """
    met = conditions(*sample, accelerated=accelerated) if sample else frozenset()
    fired: dict[str, list[dict]] = {}
    for entry in due(
        entries,
        now,
        gate_locked=gate_locked,
        conditions_met=met,
        held=held,
        blocked=blocked,
    ):
        fired.setdefault(entry["routine"], []).append(entry)
    return {routine: lane_action(group) for routine, group in sorted(fired.items())}


class Runner:
    """Start routine runs, one live run per routine, each under its agent's
    stack lock so two runs of one agent never overlap.

    Args:
        spawn: starts the argv as a child process in its own process group
            and returns it.
        wait_gate: returns once the machine's gate lock is free.
        lock_dir: the machine's lock directory.
        send: sends a signal to a process group, as ``os.killpg``.
    """

    def __init__(
        self,
        spawn: Callable[[list[str]], Process],
        wait_gate: Callable[[], None],
        lock_dir: Path,
        send: Callable[[int, int], None],
    ) -> None:
        self._spawn = spawn
        self._wait_gate = wait_gate
        self._lock_dir = lock_dir
        self._send = send
        self._runs: dict[str, Process] = {}
        self._paused: set[str] = set()
        self._lock = threading.Lock()

    def apply(
        self, routine: str, agent: str, action: str, scope: tuple[str, ...]
    ) -> str:
        """Carry out the action ``tick`` or a trigger chose for ``routine``.

        Args:
            routine: the flat routine name.
            agent: the agent role the run acts for.
            action: ``start`` or ``pause``.
            scope: the changed files a scoped start covers; empty for a full
                run.

        Raises:
            ValueError: ``action`` is neither.
        """
        if action == START:
            return self.start(routine, agent, scope)
        if action == PAUSE:
            return self.pause(routine)
        raise ValueError(f"unknown routine action {action!r}")

    def pause(self, routine: str) -> str:
        """Stop ``routine``'s live run where it stands, keeping its state, its
        connections and its stack lock; without a live run nothing happens.

        Args:
            routine: the flat routine name.
        """
        with self._lock:
            live = self._runs.get(routine)
            if live is None or live.poll() is not None:
                return IDLE
            if routine not in self._paused:
                self._send(live.pid, signal.SIGSTOP)
                self._paused.add(routine)
            return PAUSED

    def running(self) -> list[str]:
        """Return the routines with a live run."""
        with self._lock:
            return sorted(
                name for name, run in self._runs.items() if run.poll() is None
            )

    def start(self, routine: str, agent: str, scope: tuple[str, ...]) -> str:
        """Start ``routine`` for ``agent`` once the gate lock is free; a paused
        live run continues where it stopped, a running one is left alone.

        Args:
            routine: the flat routine name ``agents.routines`` discovers.
            agent: the agent role the run acts for.
            scope: the changed files a scoped run covers; empty for a full run.
        """
        self._wait_gate()
        with self._lock:
            live = self._runs.get(routine)
            if live is not None and live.poll() is None:
                if routine not in self._paused:
                    return RUNNING
                self._send(live.pid, signal.SIGCONT)
                self._paused.discard(routine)
                return RESUMED
            self._paused.discard(routine)
            lock = stack_file(self._lock_dir, agent)
            self._lock_dir.mkdir(parents=True, exist_ok=True)
            scoped = [arg for path in scope for arg in ("--scope", path)]
            self._runs[routine] = self._spawn(
                ["flock", str(lock), *ROUTINE_COMMAND, routine, *scoped]
            )
            return STARTED
