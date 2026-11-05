"""Role backends: how one engine is made writable, read-only and ranked."""

from __future__ import annotations

import abc
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class RoleError(Exception):
    """The engine refused a command or could not be reached."""


class RestartRequired(Exception):  # noqa: N818 - a signal, not an error condition
    """The engine must be killed and recovered before it may follow a writer."""


class ReseedRequired(Exception):  # noqa: N818 - a signal, not an error condition
    """The instance diverged from the writer and must be re-seeded from a peer."""


RESTART_EXIT_CODE = 3
RESEED_EXIT_CODE = 4


def run_command(argv: Sequence[str], stdin: str | None = None) -> str:
    """Run *argv* and return its stdout.

    Raises:
        RoleError: the command failed or timed out.
    """
    try:
        done = subprocess.run(
            list(argv),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RoleError(f"{argv[0]}: {error}") from error
    if done.returncode != 0:
        raise RoleError(f"{argv[0]} exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout


class Role(abc.ABC):
    """One engine instance as the elector sees it."""

    peers: Sequence[str] = ()

    def quorum(self) -> int:
        """Ranked instances a promotion needs: a majority of all instances."""
        return (len(self.peers) + 1) // 2 + 1

    @abc.abstractmethod
    def is_ready_to_compete(self) -> bool:
        """Whether the instance has caught up enough to become the writer."""

    @abc.abstractmethod
    def become_writer(self) -> None:
        """Promote the local instance; raise :class:`RoleError` on failure."""

    @abc.abstractmethod
    def become_read_only(self) -> None:
        """Make the local instance refuse writes."""

    @abc.abstractmethod
    def is_writable(self) -> bool:
        """Whether the local instance currently accepts writes."""

    @abc.abstractmethod
    def rank(self) -> Any:
        """How far the local instance has got; larger is more advanced."""

    @abc.abstractmethod
    def peer_ranks(self) -> Mapping[str, Any]:
        """The rank of every reachable peer, keyed by host id."""

    @abc.abstractmethod
    def follow(self, writer: str | None) -> None:
        """Replicate from *writer* (``None``: no writer right now)."""

    def watch(self) -> None:  # noqa: B027 - optional hook; an engine without a divergence check keeps the no-op
        """Check a following instance once per tick.

        Raises:
            ReseedRequired: the instance can no longer catch up with the writer.
        """


def choose(candidates: Mapping[str, Any]) -> str:
    """The host id that should hold the writer role.

    Highest rank wins; equal ranks go to the lowest host id, so every instance
    computing this over the same view agrees.
    """
    if not candidates:
        raise ValueError("no candidate to choose from")
    best = max(candidates.values())
    return min(host for host, rank in candidates.items() if rank == best)
