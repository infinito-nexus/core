from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from provision import provider_env

SUPERVISOR = Path(__file__).resolve().parent.with_name("tofu_supervisor.py")
GROUP_POLL_SECONDS = 0.1


class FailedError(Exception):
    """Args:
    message: the step that failed, never a credential.
    """


class BudgetError(FailedError):
    """Args:
    message: the budget the run outlived and how OpenTofu stopped.
    """


def _ended(process, deadline=None):
    """Args:
        process: the :data:`SUPERVISOR` to wait for, left unreaped so its
            zombie keeps the id of its process group reserved for
            :func:`_killed`.
        deadline: the :func:`time.monotonic` bound of the wait, ``None`` for
            none.

    Returns:
        Its exit code, negative for the signal that killed it, or ``None``
        once the deadline passed first.
    """
    flags = os.WEXITED | os.WNOWAIT | (0 if deadline is None else os.WNOHANG)
    while (info := os.waitid(os.P_PID, process.pid, flags)) is None:
        if time.monotonic() >= deadline:
            return None
        time.sleep(GROUP_POLL_SECONDS)
    return info.si_status if info.si_code == os.CLD_EXITED else -info.si_status


def _unwatched(process, deadline):
    """Args:
    process: a :data:`SUPERVISOR` a signal killed, so the rest of its
        process group, ``tofu`` included, runs on unwatched. It is reaped
        first, as its zombie would count as a member; the members that
        still run keep the group id reserved. Returns once the group is
        empty or ``deadline``, a :func:`time.monotonic` value, passed.
    """
    process.wait()
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(GROUP_POLL_SECONDS)


def _stopped(process, command):
    """Args:
        process: the :data:`SUPERVISOR` of the running ``tofu`` to stop.
        command: its subcommand, e.g. ``apply``.

    Returns:
        How ``tofu`` ended: on SIGINT within :data:`provider_env.TOFU_GRACE`,
        or killed after it, also when its supervisor died; the caller kills.

    Raises:
        Whatever a signal handler raises during the grace.
    """
    signal.alarm(0)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGINT)
    grace = provider_env.TOFU_GRACE
    deadline = time.monotonic() + grace.total_seconds()
    code = _ended(process, deadline)
    if code is None:
        return (
            f"tofu {command} ignored SIGINT for {grace} and was killed, so its "
            f"state may miss resources and keep its lock until unlock runs"
        )
    if code < 0:
        _unwatched(process, deadline)
        return (
            f"the supervisor of tofu {command} died with {code}, so its process "
            f"group got SIGINT and up to {grace} before SIGKILL, and the state "
            f"of tofu may miss resources and keep its lock until unlock runs"
        )
    return f"tofu {command} stopped on SIGINT with exit code {code}"


def _killed(process):
    """Args:
    process: the :data:`SUPERVISOR` whose process group, ``tofu`` and its
        provider plugins included, gets SIGKILL and is reaped; the group id
        stays reserved while any member lives, the unreaped supervisor too.
    """
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def tofu(task, environment, *arguments, capture=False):
    command = arguments[0]
    with subprocess.Popen(
        [sys.executable, "-I", str(SUPERVISOR), str(os.getpid()), "tofu", *arguments],
        cwd=task,
        env=environment,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        start_new_session=True,
    ) as process:
        try:
            output = process.stdout.read() if capture else ""
            code = _ended(process)
        except BaseException as stop:
            stopped = _stopped(process, command)
            if isinstance(stop, BudgetError):
                raise BudgetError(f"{stop}; {stopped}") from None
            raise
        else:
            if code < 0:
                raise FailedError(_stopped(process, command))
        finally:
            _killed(process)
    if code != 0:
        raise FailedError(f"tofu {command} exited with {code}")
    return output
