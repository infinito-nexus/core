from __future__ import annotations

import argparse
import fcntl
import os
import re
import subprocess
import time
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from utils.env.handlers.infinito.tools.idle import GRACE_KEY, STAMP_DIR_KEY

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

LAST = "last"
LOCK = "lock"
RUN_PREFIX = "run-"
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
DURATION = re.compile(r"(\d+)([smhd])")


def grace_seconds(value: str) -> int:
    """Return the idle grace ``value`` names, in seconds.

    Args:
        value: ``<count><s|m|h|d>``, e.g. ``2h``.

    Raises:
        ValueError: ``value`` is no such duration.
    """
    found = DURATION.fullmatch(value.strip())
    if not found:
        raise ValueError(f"{GRACE_KEY}={value!r} is not <count><s|m|h|d>, e.g. 2h")
    return int(found.group(1)) * UNITS[found.group(2)]


def stamp_dir(env: Mapping[str, str]) -> Path:
    """Return the machine-wide directory every tools target stamps its runs in.

    Args:
        env: the environment ``make dotenv`` wrote.

    Raises:
        RuntimeError: the environment names no such directory.
    """
    value = (env.get(STAMP_DIR_KEY) or "").strip()
    if not value:
        raise RuntimeError(f"{STAMP_DIR_KEY} is unset; run 'make dotenv'.")
    return Path(value)


@contextmanager
def _machine_lock(stamps: Path) -> Iterator[None]:
    stamps.mkdir(parents=True, exist_ok=True)
    with (stamps / LOCK).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


@contextmanager
def session(stamps: Path) -> Iterator[None]:
    """Stamp one tools target run: its start, its end, and that it runs.

    Args:
        stamps: machine-wide directory every tools target stamps in.
    """
    marker = stamps / f"{RUN_PREFIX}{uuid.uuid4().hex}"
    with ExitStack() as stack:
        with _machine_lock(stamps):
            fcntl.flock(stack.enter_context(marker.open("w")), fcntl.LOCK_EX)
            (stamps / LAST).touch()
        try:
            yield
        finally:
            (stamps / LAST).touch()
            marker.unlink(missing_ok=True)


def running(stamps: Path) -> bool:
    """Return whether a tools target runs, removing the markers of dead ones.

    Args:
        stamps: machine-wide directory every tools target stamps in.
    """
    with _machine_lock(stamps):
        return _live(stamps)


def _live(stamps: Path) -> bool:
    busy = False
    for marker in stamps.glob(f"{RUN_PREFIX}*"):
        try:
            descriptor = os.open(marker, os.O_RDONLY)
        except FileNotFoundError:
            continue
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            busy = True
        else:
            marker.unlink(missing_ok=True)
        finally:
            os.close(descriptor)
    return busy


def expired(stamps: Path, grace: int) -> bool:
    """Return whether ``grace`` seconds passed since the last stamped start or end.

    Args:
        stamps: machine-wide directory every tools target stamps in.
        grace: seconds the tools stay up after the last tools target ended.
    """
    last = stamps / LAST
    if not last.is_file():
        return True
    return time.time() - last.stat().st_mtime >= grace


def stop_if_idle(stamps: Path, grace: int, stop: Callable[[], None]) -> bool:
    """Run ``stop`` when no tools target runs and ``grace`` passed since the last one.

    Args:
        stamps: machine-wide directory every tools target stamps in.
        grace: seconds the tools stay up after the last tools target ended.
        stop: stops the tools services; it runs under the lock a starting
            tools target waits on.

    Returns:
        Whether ``stop`` ran.
    """
    with _machine_lock(stamps):
        if _live(stamps) or not expired(stamps, grace):
            return False
        stop()
        return True


def _command(argv: list[str]) -> list[str]:
    command = argv[1:] if argv[:1] == ["--"] else argv
    if not command:
        raise SystemExit("name the command after '--'")
    return command


def main(argv: list[str] | None = None) -> int:
    """Stamp a whole tools target, or stop the tools once they idle.

    Args:
        argv: ``run -- <command>`` runs the command as one stamped tools run
            and exits with its status; ``stop-if-idle -- <command>`` runs the
            stop command when :func:`stop_if_idle` decides so.
    """
    parser = argparse.ArgumentParser(description="Tools idle bookkeeping.")
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("run", "stop-if-idle"):
        commands.add_parser(action).add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = _command(args.argv)
    stamps = stamp_dir(os.environ)
    if args.action == "run":
        with session(stamps):
            return subprocess.run(command, check=False).returncode
    grace = grace_seconds(os.environ.get(GRACE_KEY) or "")

    def stop() -> None:
        subprocess.run(command, check=True)

    stopped = stop_if_idle(stamps, grace, stop)
    print("tools stopped" if stopped else "tools kept", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
