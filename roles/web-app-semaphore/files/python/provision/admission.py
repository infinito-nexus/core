from __future__ import annotations

import json
import os
import sys
from typing import NamedTuple

from provision import opentofu, sandbox, session

PROBE_SCRIPT = sandbox.SCRIPTS / "probe.py"
CREDENTIALS = session.OPENTOFU / "credentials.json"
SANDBOX_PATH = "/usr/local/bin:/usr/bin:/bin"
RUN_PATHS = frozenset({"HOME", "TMPDIR"})
CLI_CONFIG = "TF_CLI_CONFIG_FILE"
CA_NAME = "BAO_CACERT"
BAO_NAME = "BAO_ADDR"
ENCRYPTION = "TF_ENCRYPTION"
UNSAFE_CHARACTERS = ("\n", "\r", "\0")
LOCAL_FORMS = ("/", ".", "~", "file:", "unix:")
LOCAL_REMOTES = frozenset({"local"})


def credentials():
    return json.loads(CREDENTIALS.read_bytes())


class Program(NamedTuple):
    """Args:
    prefix: the argv a run of it starts with.
    names: the environment names it takes.
    arguments: checks the request's arguments against the task directory
        and returns them with the task files they name, ``None`` for a
        program that takes any.
    pinned: ``{name: the one value it takes}``, ``None`` for a name the
        layout leaves unset, which no run may pass.
    files: the names whose value is a file below the task directory.
    endpoints: the names whose value is the address of a provider API,
        tenant data that may name no local path.
    """

    prefix: list
    names: frozenset
    arguments: object
    pinned: dict
    files: frozenset
    endpoints: frozenset


def pinned_values(environ, cli_config, ca, bao_addr):
    """Args:
        environ: the environment of the spawner.
        cli_config: the CLI configuration of the image.
        ca: the CA file of the layout, ``None`` when the layout has none.
        bao_addr: the OpenBao address of the layout.

    Returns:
        :attr:`Program.pinned` of ``tofu``: every name of
        :data:`sandbox.PASSED` but ``PATH`` as the spawner's own environment
        holds it, the image's CLI configuration, the layout's OpenBao
        address and its CA file, ``None`` without one, so no run passes
        ``BAO_CACERT`` then. A name ``credentials.json`` points below the
        task's ``credentials`` directory, such as ``SSL_CERT_DIR`` of
        ``proxmox``, is a task file of ``tofu`` instead and not pinned.
    """
    unpinned = {"PATH"} | session.credential_file_names(credentials())
    values = {name: environ.get(name) for name in sandbox.PASSED - unpinned}
    return values | {
        CLI_CONFIG: str(cli_config),
        CA_NAME: None if ca is None else str(ca),
        BAO_NAME: bao_addr,
    }


def programs(tofu, specs, pinned):
    """Args:
        tofu: the ``tofu`` binary of the image.
        specs: the decoded ``credentials.json``.
        pinned: :func:`pinned_values`.

    Returns:
        ``{program: Program}`` of every run a sandbox admits: ``tofu`` with
        the names and commands the provision code uses, and the live probe
        with its own names.
    """
    return {
        sandbox.TOFU: Program(
            [str(tofu)],
            session.tofu_names(specs),
            opentofu.admitted_arguments,
            pinned,
            session.credential_file_names(specs),
            session.endpoint_names(specs),
        ),
        sandbox.PROBE: Program(
            [sys.executable, *sandbox.ISOLATED, str(PROBE_SCRIPT), sandbox.PROBE],
            sandbox.PROBE_NAMES,
            None,
            {},
            frozenset(),
            frozenset(),
        ),
    }


def value_admitted(name, value, entry, task):
    """Args:
        name: an environment name a program takes.
        value: the value the request gives it.
        entry: the :class:`Program`.
        task: the task directory of the sandbox.

    Returns:
        Whether the run may get it: no value with a line break or NUL; a
        pinned name only its pinned value; ``HOME`` and ``TMPDIR`` only the
        run's home; a file name only a file below the task directory;
        ``TF_ENCRYPTION`` only what :func:`session.encryption` writes; an
        endpoint, in any case, no local path or socket and no remote of
        :data:`LOCAL_REMOTES`, the Incus daemon of the host's own socket;
        any other value, a secret included, as it is.
    """
    if any(character in value for character in UNSAFE_CHARACTERS):
        return False
    if name in entry.pinned:
        return entry.pinned[name] is not None and value == entry.pinned[name]
    if name in RUN_PATHS:
        return value == str(sandbox.home_of(task))
    if name in entry.files:
        return sandbox.task_relative(task, value) is not None
    if name == ENCRYPTION:
        return session.is_encryption(value)
    if name in entry.endpoints:
        form = value.strip().lower()
        return not (
            form.startswith(LOCAL_FORMS) or form.partition(":")[0] in LOCAL_REMOTES
        )
    return True


def admitted(message, known, task):
    """Args:
        message: a ``run`` request of the runner.
        known: :func:`programs`.
        task: the task directory of the sandbox.

    Returns:
        ``(argv, env, files)`` of the run: the program's own prefix, then the
        request's arguments, its environment with the spawner's own ``PATH``,
        and the task files it names, relative to ``task``.

    Raises:
        SandboxError: the request names another program, carries an argument
            or a value that is no text, a name the program does not take, a
            value :func:`value_admitted` refuses or an argument the program's
            check refuses; no refusal names a value.
    """
    program, arguments, environment = (
        message.get(key) for key in ("program", "argv", "env")
    )
    if not isinstance(program, str) or program not in known:
        raise sandbox.SandboxError(f"a sandbox runs only {', '.join(sorted(known))}")
    entry = known[program]
    if not isinstance(arguments, list) or not all(
        isinstance(argument, str) for argument in arguments
    ):
        raise sandbox.SandboxError(f"the arguments of {program} are no texts")
    if not isinstance(environment, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in environment.items()
    ):
        raise sandbox.SandboxError(f"the environment of {program} maps no texts")
    foreign = sorted(set(environment) - set(entry.names))
    if foreign:
        raise sandbox.SandboxError(f"{program} takes no {', '.join(foreign)}")
    refused = sorted(
        name
        for name, value in environment.items()
        if name != "PATH" and not value_admitted(name, value, entry, task)
    )
    if refused:
        raise sandbox.SandboxError(f"{program} takes no such {', '.join(refused)}")
    files = [
        str(sandbox.task_relative(task, value))
        for name, value in environment.items()
        if name in entry.files
    ]
    if entry.arguments is not None:
        arguments, named = entry.arguments(arguments, task)
        files += named
    environment = environment | {"PATH": SANDBOX_PATH}
    return [*entry.prefix, *arguments], environment, files


def exec_plan(descriptor, run=os.execvpe):
    """Args:
    descriptor: the pipe the spawner writes ``{argv, env, cwd, files}`` to.
    run: replaces this process with ``argv`` in ``cwd`` and exactly ``env``,
        once no task file of ``files`` lies behind a link; root may not
        search the task directory, so this helper checks it as the sandbox
        uid.
    """
    with os.fdopen(descriptor, encoding="utf-8") as handle:
        plan = json.load(handle)
    for relative in plan["files"]:
        if sandbox.linked(plan["cwd"], relative):
            raise SystemExit(f"sandbox/spawner.py:{relative} lies behind a link")
    os.chdir(plan["cwd"])
    run(plan["argv"][0], plan["argv"], plan["env"])
