"""Args:
serve <command> [<argument> ...]: as root, the entry point of the provision
    runner: it closes the temporary directory ``SEMAPHORE_SANDBOX_TMP`` and
    the shared writable directories ``SEMAPHORE_SANDBOX_SHARED`` names,
    separated by ``:``, starts ``command``, the Semaphore runner, as the uid
    ``SEMAPHORE_SANDBOX_RUNNER_UID`` names and serves one OpenTofu sandbox per
    run to that uid alone below ``SEMAPHORE_SANDBOX_ROOT``, each under a uid
    of its own from ``SEMAPHORE_SANDBOX_UID_BASE`` on, at most
    ``SEMAPHORE_SANDBOX_UID_COUNT`` of them.
signal <signal> [<pid>]: as a sandbox uid, sends ``signal`` to ``pid``, or to
    every process of that uid without a pid.
purge <directory> ...: as one uid, removes every entry that uid owns below
    each directory.
ipc: as a sandbox uid, removes every System V IPC object of that uid.
exec <descriptor>: as a sandbox uid, reads ``{argv, env, cwd}`` from the
    descriptor and execs ``argv`` in ``cwd`` with exactly ``env``.
broker <login> <openbao> <ca>: as the broker uid ``SEMAPHORE_SANDBOX_BROKER_UID``
    names, serves the DNS broker of ``provision/dns/broker.py`` with the
    AppRole file ``login`` only that uid reads, ``serve`` starting it beside
    the Semaphore runner.
"""

from __future__ import annotations

import contextlib
import ctypes
import functools
import os
import pwd
import signal
import socket
import struct
import sys
import threading
import time
from pathlib import Path

# nocheck: project-root-import  the runner image starts this script and its helpers by path with python3 -E -s, so only its own folder is on sys.path; the provision package lies one folder up in files/python
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from provision import admission, hardening, privileged, sandbox, session
from provision.dns import broker as dns_broker

PROC = sandbox.PROC
BROKER = "broker"
PEERCRED = struct.Struct("3i")
KILL_ROUNDS = 200
KILL_PAUSE = 0.05
ACCEPT_PAUSE = 1.0


class Spawner:
    """Args:
    privileges: the :class:`privileged.Privileges` the sandboxes run with.
    root: the directory holding every sandbox.
    uids: the range of sandbox uids, disjoint from the runner's uid and from
        the uids of the workspace runners.
    known: :func:`admission.programs`, every run a sandbox admits.
    """

    def __init__(self, privileges, root, uids, known):
        self.privileges = privileges
        self.root = Path(root)
        self.uids = uids
        self.known = known
        self.active = set()
        self.quarantined = set()
        self.lock = threading.Lock()

    def quarantine(self, uid, reason):
        """Args:
        uid: a uid that stays out of the range for the life of the spawner;
            stderr says so, naming ``reason``.
        reason: why, never a credential.
        """
        with self.lock:
            self.active.discard(uid)
            self.quarantined.add(uid)
        print(
            f"sandbox/spawner.py: the uid {uid} stays out of the range: {reason}",
            file=sys.stderr,
        )

    def allocate(self):
        """Returns:
        The lowest uid of the range that no open sandbox holds, no process
        holds and that owns no entry anywhere the walk of
        :meth:`privileged.Privileges.leftovers` reaches.

        Raises:
            SandboxError: every uid of the range is taken.
        """
        with self.lock:
            for uid in self.uids:
                if uid in self.active or uid in self.quarantined:
                    continue
                if sandbox.run_directory(self.root, uid).exists():
                    continue
                if (
                    self.privileges.holders(uid)
                    or self.privileges.ipc_left(uid)
                    or self.privileges.leftovers(uid)
                ):
                    continue
                self.active.add(uid)
                return uid
        raise sandbox.SandboxError("every sandbox uid is taken")

    def open(self):
        """Returns:
        ``(uid, task directory)`` of a new sandbox.
        """
        uid = self.allocate()
        entries = sandbox.layout(self.root, uid, self.privileges.runner)
        try:
            self.privileges.prepare(entries)
        except BaseException:
            self.close(uid)
            raise
        return uid, entries[1][0]

    def kill(self, uid):
        """Returns:
        Once no process of ``uid`` lives, whichever session or process group
        it started.

        Raises:
            SandboxError: one still lives after every round.
        """
        for _round in range(KILL_ROUNDS):
            if not self.privileges.holders(uid):
                return
            self.privileges.signal_all(uid, signal.SIGKILL)
            time.sleep(KILL_PAUSE)
        if self.privileges.holders(uid):
            raise sandbox.SandboxError(f"a process of the sandbox {uid} survived")

    def close(self, uid):
        """Returns:
        Once every process of ``uid`` is dead and every file of its run is
        gone; only then the uid returns to the range, else it stays out of it
        for the life of the spawner and stderr says so, as each such uid
        shrinks the range of :data:`hardening.UID_COUNT` until the container
        restarts.
        """
        run = sandbox.run_directory(self.root, uid)
        task = run / sandbox.TASK
        try:
            self.kill(uid)
            if run.exists():
                self.privileges.purge(uid, task, sandbox.home_of(task))
        except BaseException as failure:
            self.quarantine(uid, failure)
            raise
        with self.lock:
            if uid not in self.quarantined:
                self.active.discard(uid)

    def serve(self, connection):
        """Args:
        connection: an accepted connection, closed on every path; only the
            runner uid is served, and it opens exactly one sandbox on it,
            :data:`sandbox.QUEUED` answering the open before :meth:`open`
            waits for :attr:`lock`.
        """
        channel = sandbox.Channel(connection)
        with connection:
            try:
                _pid, uid, _gid = PEERCRED.unpack(
                    connection.getsockopt(
                        socket.SOL_SOCKET, socket.SO_PEERCRED, PEERCRED.size
                    )
                )
                message, descriptors = channel.receive()
                sandbox.close_all(descriptors)
                if uid != self.privileges.runner or message != {"op": "open"}:
                    return
                channel.send(sandbox.QUEUED)
                try:
                    box, task = self.open()
                except (sandbox.SandboxError, OSError) as refusal:
                    channel.send({"error": str(refusal)})
                    return
                try:
                    channel.send({"uid": box, "task": str(task)})
                    Run(self, channel, box, task).serve()
                finally:
                    with contextlib.suppress(sandbox.SandboxError, OSError):
                        self.close(box)
                        channel.send({"closed": True})
            finally:
                channel.close_descriptors()


class Run:
    """Args:
    spawner: the :class:`Spawner`.
    channel: the channel of the runner's process that opened the sandbox.
    uid: the uid of the sandbox.
    task: its task directory.
    """

    def __init__(self, spawner, channel, uid, task):
        self.spawner = spawner
        self.channel = channel
        self.uid = uid
        self.task = task
        self.waiter = None
        self.survived = False

    def finish(self, process):
        code = self.spawner.privileges.wait(process)
        reply = self.cleared() or {"exit": code}
        with contextlib.suppress(OSError):
            self.channel.send(reply)

    def cleared(self):
        """Returns:
        ``None`` once no process of the uid lives, else the error reply that
        names the survivor, whose uid stays quarantined.
        """
        try:
            self.spawner.kill(self.uid)
        except sandbox.SandboxError as survivor:
            self.survived = True
            self.spawner.quarantine(self.uid, survivor)
            return {"error": str(survivor)}
        return None

    def serve(self):
        """Returns:
        Once the runner's process closes the sandbox or its connection, or
        a receive raised, with no process of the sandbox alive and the waiter
        of its last run ended.
        """
        try:
            while True:
                message, descriptors = self.channel.receive()
                try:
                    if message is None or message.get("op") == "close":
                        break
                    self.handle(message, descriptors)
                finally:
                    sandbox.close_all(descriptors)
        finally:
            self.spawner.kill(self.uid)
            if self.waiter is not None:
                self.waiter.join()

    def handle(self, message, descriptors):
        privileges = self.spawner.privileges
        if message.get("op") == "run" and len(descriptors) == sandbox.STREAMS:
            self.run(message, descriptors)
        elif message.get("op") == "signal":
            privileges.signal_all(self.uid, int(message["signal"]))
        elif message.get("op") == "kill":
            privileges.signal_all(self.uid, signal.SIGKILL)

    def run(self, message, descriptors):
        if self.waiter is not None:
            self.waiter.join()
        if self.survived:
            self.channel.send(
                {
                    "error": f"a process of the sandbox {self.uid} survived, "
                    "so it runs nothing more"
                }
            )
            return
        try:
            argv, environment, files = admission.admitted(
                message, self.spawner.known, self.task
            )
        except sandbox.SandboxError as refusal:
            self.channel.send({"error": str(refusal)})
            return
        privileges = self.spawner.privileges
        process = privileges.start(
            self.uid, self.task, argv, environment, descriptors, files
        )
        waiter = threading.Thread(target=self.finish, args=(process,))
        try:
            waiter.start()
        except RuntimeError as failure:
            privileges.signal_all(self.uid, signal.SIGKILL)
            privileges.wait(process)
            reply = {"error": f"no waiter of the run started: {failure}"}
            self.channel.send(self.cleared() or reply)
            return
        self.waiter = waiter


def refused(what, failure):
    """Args:
    what: what the accept loop could not do.
    failure: why; stderr names both and the type of ``failure`` unless it is
        closed itself, and the loop goes on after :data:`ACCEPT_PAUSE`.
    """
    with contextlib.suppress(OSError, ValueError):
        print(
            f"sandbox/spawner.py: {what}: {type(failure).__name__}: {failure}",
            file=sys.stderr,
        )
    time.sleep(ACCEPT_PAUSE)


def accept(listener, serve_connection):
    """Args:
        listener: the listening socket of the spawner.
        serve_connection: what serves an accepted connection, each in a
            thread of its own.

    Returns:
        Never: an ``OSError`` of a failed accept, ``EMFILE`` among them, and
        the ``RuntimeError`` of a thread that cannot start, whose connection
        is closed, go to :func:`refused`, so no run waits on a spawner that
        stopped accepting; every other exception, a ``BaseException`` that
        is no ``Exception`` included, propagates and ends the loop with its
        traceback on stderr, and :func:`vital` then ends the spawner.
    """
    while True:
        try:
            connection, _address = listener.accept()
        except OSError as failure:
            refused("no connection accepted", failure)
            continue
        try:
            threading.Thread(
                target=serve_connection, args=(connection,), daemon=True
            ).start()
        except RuntimeError as failure:
            with contextlib.suppress(OSError):
                connection.close()
            refused("no connection served", failure)


def vital(target):
    """Args:
        target: what a thread of the spawner runs that it cannot serve
            without.

    Returns:
        ``target`` wrapped to send ``SIGTERM`` to the spawner once it ends,
        whichever way, so the handler :func:`serve` installs stops the
        Semaphore runner and the container restarts instead of keeping a
        runner that no sandbox serves.
    """

    @functools.wraps(target)
    def running(*arguments):
        try:
            target(*arguments)
        finally:
            os.kill(os.getpid(), signal.SIGTERM)

    return running


def broker_argv(container):
    """Args:
        container: :func:`hardening.layout`.

    Returns:
        The command that serves the DNS broker as its own uid, with the
        AppRole file, the OpenBao address and the CA file of the layout, an
        empty CA for none; the spawner passes it only ``PATH``.
    """
    ca = "" if container["ca"] is None else str(container["ca"])
    script = str(Path(__file__).resolve())
    argv = [sys.executable, *sandbox.ISOLATED, script, BROKER]
    return sandbox.dropped(
        container["broker"], [*argv, str(container["login"]), container["bao"], ca]
    )


def broker_ended(process):
    """Args:
        process: the DNS broker :func:`serve` started.

    Returns:
        Once the broker ended, which :func:`vital` turns into the end of the
        spawner, so no run reaches a DNS provider through a broker that is
        gone.
    """
    privileged.waited(process)


def serve(argv):
    """Args:
        argv: the command of the Semaphore runner and its arguments.

    Returns:
        The exit code of the Semaphore runner.
    """
    container = hardening.layout(os.environ)
    if os.geteuid() != 0:
        raise SystemExit("sandbox/spawner.py:serve needs root")
    hardening.no_new_privileges(ctypes.CDLL(None, use_errno=True))
    runner = container["runner"]
    skipped = (container["root"], container["tmp"])
    privileges = privileged.Privileges(runner, PROC, sandbox.FILESYSTEM, skipped)
    pinned = admission.pinned_values(
        os.environ, session.OPENTOFU / "tofurc", container["ca"], container["bao"]
    )
    spawner = Spawner(
        privileges,
        container["root"],
        container["uids"],
        admission.programs(container["tofu"], admission.credentials(), pinned),
    )
    listener = hardening.harden(
        runner,
        pwd.getpwuid(runner).pw_gid,
        container["root"],
        container["tmp"],
        container["shared"],
        sandbox.FILESYSTEM,
    )
    process = privileged.spawned(
        sandbox.dropped(runner, argv), env=hardening.runner_environment(runner)
    )

    def stop(signum, _frame):
        privileges.helper(runner, "signal", str(signum), str(process.pid))

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    broker = privileged.spawned(
        broker_argv(container), env={"PATH": admission.SANDBOX_PATH}
    )
    threading.Thread(
        target=vital(accept), args=(listener, spawner.serve), daemon=True
    ).start()
    threading.Thread(target=vital(broker_ended), args=(broker,), daemon=True).start()
    threading.Thread(target=privileged.reap, daemon=True).start()
    code = privileged.waited(process)
    for uid in sorted(spawner.active):
        with contextlib.suppress(sandbox.SandboxError):
            spawner.kill(uid)
    return code if code >= 0 else 128 - code


def main(argv):
    """Args:
        argv: ``[script, mode, *arguments]``; see the module documentation.

    Returns:
        The exit code.
    """
    mode, arguments = argv[1], argv[2:]
    if mode == "serve":
        return serve(arguments)
    if mode == "signal":
        target = int(arguments[1]) if len(arguments) > 1 else -1
        with contextlib.suppress(ProcessLookupError):
            os.kill(target, int(arguments[0]))
        return 0
    if mode == "purge":
        privileged.remove_owned(*arguments)
        return 0
    if mode == "ipc":
        privileged.remove_ipc(os.getuid(), ctypes.CDLL(None, use_errno=True), PROC)
        return 0
    if mode == "exec":
        admission.exec_plan(int(arguments[0]))
    if mode == BROKER:
        dns_broker.serve(*arguments)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
