"""Owner holds and owner-only blockers, the machine state next to the gate lock.

A hold is a newer, specific owner instruction ("pause the translation until I
release it") that outranks every later cron firing of the routine. A blocker
is something only the owner can decide (a missing credential, a scope
question); it is reported once and keeps every cron from starting the
routine. Both are written through to one JSON file on the orchestrator's
state volume, so they survive a restart, and only the owner sets or lifts
them through the management API.
"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

HOLDS = "holds"
BLOCKERS = "blockers"


class Store:
    """The holds and blockers of one orchestrator.

    Args:
        path: the JSON file on the state volume; read when present.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        state = {}
        if path.is_file():
            with path.open(encoding="utf-8") as handle:
                state = json.load(handle)
        self._holds: dict[str, dict] = dict(state.get(HOLDS) or {})
        self._blockers: dict[str, dict] = dict(state.get(BLOCKERS) or {})

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        staged = self._path.with_suffix(".tmp")
        staged.write_text(
            json.dumps(
                {HOLDS: self._holds, BLOCKERS: self._blockers},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        staged.replace(self._path)

    def held(self) -> frozenset[str]:
        """Return the routines on hold."""
        with self._lock:
            return frozenset(self._holds)

    def blocked(self) -> frozenset[str]:
        """Return the routines with an open blocker."""
        with self._lock:
            return frozenset(self._blockers)

    def blockers(self) -> dict[str, dict]:
        """Return every open blocker with its evidence."""
        with self._lock:
            return dict(self._blockers)

    def hold(self, routine: str, instruction: str) -> bool:
        """Put ``routine`` on hold until the owner lifts it; return whether it
        was not on hold before.

        Args:
            routine: the flat routine name.
            instruction: the owner's instruction, recorded with the hold.
        """
        with self._lock:
            new = routine not in self._holds
            self._holds[routine] = {"instruction": instruction}
            self._write()
            return new

    def lift(self, routine: str) -> bool:
        """Lift the hold on ``routine``; return whether one was set.

        Args:
            routine: the flat routine name.
        """
        with self._lock:
            lifted = self._holds.pop(routine, None) is not None
            self._write()
            return lifted

    def block(self, routine: str, evidence: str) -> bool:
        """Record an owner-only blocker on ``routine``; return ``True`` only
        for a new blocker, so the caller reports it once.

        Args:
            routine: the flat routine name.
            evidence: what the routine found, recorded with the blocker.
        """
        with self._lock:
            if routine in self._blockers:
                return False
            self._blockers[routine] = {"evidence": evidence}
            self._write()
            return True

    def clear(self, routine: str) -> bool:
        """Clear the blocker on ``routine``; return whether one was open.

        Args:
            routine: the flat routine name.
        """
        with self._lock:
            cleared = self._blockers.pop(routine, None) is not None
            self._write()
            return cleared
