"""Find the host processes that already listen on a public port the deploy
binds. A socket of docker itself, or of a process inside a container (a
host-networked one such as the edge proxy), belongs to the deploy and passes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

DOCKER_PROCESSES = frozenset({"docker-proxy", "dockerd"})

_PROCESS = re.compile(r'\("((?:[^"\\]|\\.)*)",pid=(\d+)')
_CGROUP_LINE = re.compile(r"^/proc/(\d+)/cgroup:(.*)$")
_CONTAINER_CGROUP = re.compile(r"/(?:docker|libpod)[-/][0-9a-f]{12,}")


@dataclass(frozen=True)
class Listener:
    """One listening socket of ``ss -Htlnpu``."""

    protocol: str
    address: str
    port: int
    processes: tuple[tuple[str, int], ...]


def parse_listeners(output: str) -> list[Listener]:
    """Split the output of ``ss -Htlnpu`` into its sockets.

    Args:
        output: the stdout of ``ss -Htlnpu``, run as root so every socket
            names its processes.

    Returns:
        One :class:`Listener` per line; ``processes`` is empty for a socket
        ss names no process for, such as one the kernel holds.

    Raises:
        ValueError: a line has no local ``address:port`` column.
    """
    listeners: list[Listener] = []
    for line in output.splitlines():
        fields = line.split()
        if not fields:
            continue
        if len(fields) < 6 or ":" not in fields[4]:
            raise ValueError(f"unparsable ss line: {line!r}")
        address, _, port = fields[4].rpartition(":")
        if not port.isdigit():
            raise ValueError(f"unparsable ss line: {line!r}")
        processes = tuple(
            (name, int(pid)) for name, pid in _PROCESS.findall(" ".join(fields[6:]))
        )
        listeners.append(Listener(fields[0], address, int(port), processes))
    return listeners


def _held(
    listeners: Iterable[Listener], ports: Mapping[int, object]
) -> Iterator[Listener]:
    for listener in listeners:
        if listener.port in ports:
            yield listener


def suspect_pids(
    listeners: Iterable[Listener], ports: Mapping[int, object]
) -> list[int]:
    """The processes on a deploy port whose cgroup decides whether they pass.

    Args:
        listeners: the sockets of the host, as :func:`parse_listeners` returns them.
        ports: every public port the deploy binds, as keys.

    Returns:
        The sorted PIDs of every process other than docker's own that
        listens on one of ``ports``.
    """
    return sorted(
        {
            pid
            for listener in _held(listeners, ports)
            for name, pid in listener.processes
            if name not in DOCKER_PROCESSES
        }
    )


def containerised_pids(output: str) -> set[int]:
    """The PIDs whose cgroup is a container's.

    Args:
        output: the stdout of ``grep -H . /proc/<pid>/cgroup ...``.

    Returns:
        Every PID with a cgroup line naming a docker or podman container.
    """
    pids: set[int] = set()
    for line in output.splitlines():
        match = _CGROUP_LINE.match(line.strip())
        if match and _CONTAINER_CGROUP.search(match.group(2)):
            pids.add(int(match.group(1)))
    return pids


def probed_pids(output: str) -> set[int]:
    """The PIDs that still ran when their cgroup was read.

    Args:
        output: the stdout of ``grep -H . /proc/<pid>/cgroup ...``.

    Returns:
        Every PID with at least one cgroup line.
    """
    return {
        int(match.group(1))
        for line in output.splitlines()
        if (match := _CGROUP_LINE.match(line.strip()))
    }


def port_conflicts(
    listeners: Iterable[Listener],
    containerised: set[int],
    ports: Mapping[int, Iterable[str]],
    probed: set[int],
) -> list[str]:
    """Every deploy port a host process outside docker already listens on.

    Args:
        listeners: the sockets of the host, as :func:`parse_listeners` returns them.
        containerised: the PIDs that run inside a container, as
            :func:`containerised_pids` returns them.
        ports: public port -> every ``<role> (<service>.<name>)`` that binds it.
        probed: the PIDs whose cgroup could still be read, as
            :func:`probed_pids` returns them. A PID ss listed that exited
            before its cgroup was read no longer holds the port.

    Returns:
        One message per conflicting socket, naming the port, the protocol, the
        address, the holding processes and the roles that bind the port. A
        socket held only by docker or containerised processes passes; one
        that names no process at all is a conflict, since nothing shows it
        belongs to docker.
    """
    errors: list[str] = []
    for listener in _held(listeners, ports):
        foreign = [
            (name, pid)
            for name, pid in listener.processes
            if name not in DOCKER_PROCESSES
            and pid in probed
            and pid not in containerised
        ]
        if listener.processes and not foreign:
            continue
        holders = (
            ", ".join(f"{name} (pid {pid})" for name, pid in foreign)
            or "a socket without a process"
        )
        errors.append(
            f"{holders} listens on {listener.protocol} {listener.address}:"
            f"{listener.port}, which {' and '.join(sorted(ports[listener.port]))} binds"
        )
    return errors
