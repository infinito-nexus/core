from __future__ import annotations

import os
import re
import select
import signal
import sys

from provision import provider_env, sandbox

READ_BYTES = 65536
LOCK_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TASK_FILE_FLAGS = frozenset({"-backend-config", "-var-file"})
COMMANDS = {
    ("init",): (frozenset({"-input=false", "-backend-config"}), None),
    ("state", "list"): (frozenset(), None),
    ("output",): (frozenset({"-json"}), None),
    ("show",): (frozenset({"-json"}), None),
    ("apply",): (frozenset({"-auto-approve", "-input=false", "-var-file"}), None),
    ("destroy",): (frozenset({"-auto-approve", "-input=false", "-var-file"}), None),
    ("force-unlock",): (frozenset({"-force"}), LOCK_ID),
}


class FailedError(Exception):
    """Args:
    message: the step that failed, never a credential.
    """


class BudgetError(FailedError):
    """Args:
    message: the budget the run outlived and how OpenTofu stopped.
    """


def _stopped(box, command):
    """Args:
        box: the :class:`sandbox.Sandbox` of the running ``tofu`` to stop.
        command: its subcommand, e.g. ``apply``.

    Returns:
        How ``tofu`` ended: on SIGINT within :data:`provider_env.TOFU_GRACE`,
        or killed with every process of its sandbox after it.

    Raises:
        Whatever a signal handler raises during the grace.
    """
    signal.alarm(0)
    box.signal(signal.SIGINT)
    grace = provider_env.TOFU_GRACE
    code = box.ended(grace.total_seconds())
    if code is None:
        box.kill()
        return (
            f"tofu {command} ignored SIGINT for {grace} and was killed, so its "
            f"state may miss resources and keep its lock until unlock runs"
        )
    return f"tofu {command} stopped on SIGINT with exit code {code}"


def admitted_arguments(arguments, task):
    """Args:
        arguments: the subcommand and arguments a run asks ``tofu`` for.
        task: the task directory of its sandbox.

    Returns:
        ``(arguments, files)``, once the arguments start with a command of
        :data:`COMMANDS` and every further one is a flag that command takes,
        its lock id, or a flag of :data:`TASK_FILE_FLAGS` in its file form
        naming a file below ``task``; ``files`` are those files relative to
        ``task``, which the sandbox uid checks for links before ``tofu``
        starts.

    Raises:
        SandboxError: any other argument, such as ``-chdir=``,
            ``-plugin-dir=`` or ``-backend-config=<key>=<value>``; the refusal
            names the flag, never its value.
    """
    words = next(
        (words for words in COMMANDS if tuple(arguments[: len(words)]) == words),
        None,
    )
    if words is None:
        raise sandbox.SandboxError("tofu runs no such command in a sandbox")
    flags, positional = COMMANDS[words]
    files = []
    for argument in arguments[len(words) :]:
        flag, equals, value = argument.partition("=")
        if argument in flags - TASK_FILE_FLAGS or (
            positional and positional.match(argument)
        ):
            continue
        relative = sandbox.task_relative(task, value)
        if (
            equals
            and flag in flags & TASK_FILE_FLAGS
            and "=" not in value
            and relative is not None
        ):
            files.append(str(relative))
            continue
        raise sandbox.SandboxError(f"tofu {' '.join(words)} takes no {flag}")
    return list(arguments), files


def _drained(reader, box):
    """Args:
        reader: the read end of the stdout pipe of ``tofu``.
        box: its :class:`sandbox.Sandbox`.

    Returns:
        ``(stdout, exit code)``; the pipe is read to its end only once the
        spawner reported the end of the run, as no process of the sandbox
        holds it then.

    Raises:
        SandboxError: the spawner broke off the run, as a process of the
            sandbox survived and may hold the pipe open for ever.
    """
    chunks = []
    connection = box.channel.connection
    code = None
    while code is None:
        readable, _, _ = select.select([reader, connection], [], [])
        chunk = os.read(reader, READ_BYTES) if reader in readable else b""
        chunks.append(chunk)
        if connection in readable or (reader in readable and not chunk):
            code = box.ended()
    while chunk := os.read(reader, READ_BYTES):
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8"), code


def tofu(task, environment, *arguments, capture=False):
    """Args:
        task: the task directory of the run's sandbox, see :func:`sandbox.opened`.
        environment: the environment of ``tofu``, passed as it is.
        arguments: the subcommand and its arguments.
        capture: whether to return the stdout of ``tofu`` instead of passing it.

    Returns:
        The captured stdout, ``""`` without ``capture``, once ``tofu`` ended
        and no process of the sandbox lives, one that left its process group
        or session included.

    Raises:
        FailedError: ``tofu`` failed or a signal killed it.
        BudgetError: the run outlived its budget; ``tofu`` got SIGINT first.
    """
    command = arguments[0]
    box = sandbox.of(task)
    reader, writer = os.pipe() if capture else (None, sys.stdout.fileno())
    try:
        try:
            box.start(sandbox.TOFU, arguments, environment, writer)
        finally:
            if capture:
                os.close(writer)
        try:
            output, code = _drained(reader, box) if capture else ("", box.ended())
        except BaseException as stop:
            if not box.running:
                raise
            try:
                stopped = _stopped(box, command)
            finally:
                box.kill()
            if isinstance(stop, BudgetError):
                raise BudgetError(f"{stop}; {stopped}") from None
            raise
    finally:
        if capture:
            os.close(reader)
    if code < 0:
        raise FailedError(
            f"tofu {command} was killed by signal {-code}, so its state may miss "
            f"resources and keep its lock until unlock runs"
        )
    if code != 0:
        raise FailedError(f"tofu {command} exited with {code}")
    return output
