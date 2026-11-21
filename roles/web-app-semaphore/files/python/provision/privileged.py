from __future__ import annotations

import contextlib
import json
import os
import stat
import subprocess
import sys
import threading
import time

from provision import sandbox

ENTRY = sandbox.SCRIPTS / "spawner.py"
IPC_RMID = 0
IPC_REMOVERS = {"shm": "shmctl", "msg": "msgctl", "sem": "semctl"}
HELPER_PATH = os.defpath
REAP_SECONDS = 1.0
CHILDREN = set()
CHILDREN_LOCK = threading.RLock()


def spawned(argv, **options):
    """Args:
        argv: the command.
        options: further :class:`subprocess.Popen` options.

    Returns:
        The process, its pid in :data:`CHILDREN` before it can exit.
    """
    with CHILDREN_LOCK:
        process = subprocess.Popen(argv, **options)
        CHILDREN.add(process.pid)
    return process


def waited(process):
    code = process.wait()
    with CHILDREN_LOCK:
        CHILDREN.discard(process.pid)
    return code


def children(proc):
    """Args:
        proc: the proc filesystem.

    Returns:
        The pids of every process whose parent is this one, an orphan the
        kernel handed to this PID 1 among them, in no particular order.
    """
    parent = str(os.getpid())
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "stat").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        fields = status.rsplit(")", 1)[-1].split()
        if len(fields) > 1 and fields[1] == parent:
            found.append(int(entry.name))
    return found


def reap_round():
    """Returns:
    Once every child that exited and that :func:`spawned` did not start is
    reaped, each by its own pid, so a child the spawner still waits for
    never hides an orphan behind it, whichever exited first.
    """
    with CHILDREN_LOCK:
        for pid in children(sandbox.PROC):
            if pid not in CHILDREN:
                with contextlib.suppress(ChildProcessError):
                    os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG)


def reap():
    while True:
        time.sleep(REAP_SECONDS)
        reap_round()


def uids_of(entry):
    """Args:
        entry: ``/proc/<pid>`` of a process.

    Returns:
        Its real, effective, saved and filesystem uid, none once it ended.
    """
    try:
        status = (entry / "status").read_bytes().decode("utf-8", "replace")
    except OSError:
        return []
    return [
        field
        for line in status.splitlines()
        if line.startswith("Uid:")
        for field in line.split()[1:]
    ]


def holders(uid, proc=sandbox.PROC):
    """Args:
        uid: a sandbox uid.
        proc: the proc filesystem.

    Returns:
        The pids of every process whose real, effective, saved or filesystem
        uid is ``uid``.
    """
    return [
        int(entry.name)
        for entry in proc.iterdir()
        if entry.name.isdigit() and str(uid) in uids_of(entry)
    ]


def owner(info):
    """Args:
        info: the ``lstat`` result of an entry, a symbolic link itself
            included.

    Returns:
        The uid that owns it.
    """
    return info.st_uid


def owned(uid, top, skipped):
    """Args:
        uid: a sandbox uid.
        top: see :func:`sandbox.walked`.
        skipped: see :func:`sandbox.walked`.

    Returns:
        Every entry of a directory of :func:`sandbox.walked` that ``uid`` owns.
    """
    found = []
    for directory in sandbox.walked(top, skipped):
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            path = directory / name
            with contextlib.suppress(FileNotFoundError):
                if owner(os.lstat(path)) == uid:
                    found.append(path)
    return found


def remove_owned(*tops):
    """Args:
    tops: directories below which every entry this uid owns goes; an own
        directory is opened up first so nothing in it stays hidden, and a
        directory keeps whatever another uid left in it.
    """
    uid = os.getuid()
    for top in tops:
        for _directory, names, _files, descriptor in os.fwalk(top):
            for name in names:
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode) and owner(info) == uid:
                    os.chmod(name, 0o700, dir_fd=descriptor)
        for _directory, names, files, descriptor in os.fwalk(top, topdown=False):
            for name in [*files, *names]:
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if owner(info) != uid:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    with contextlib.suppress(OSError):
                        os.rmdir(name, dir_fd=descriptor)
                else:
                    os.unlink(name, dir_fd=descriptor)


def remove_ipc(uid, libc, proc):
    """Args:
    uid: the uid this helper runs as.
    libc: the C library whose ``shmctl``, ``msgctl`` and ``semctl`` remove
        an object of that uid.
    proc: the proc filesystem.
    """
    for kind, identifier in sandbox.ipc_objects(uid, proc):
        remover = getattr(libc, IPC_REMOVERS[kind])
        if kind == "sem":
            remover(int(identifier), 0, IPC_RMID)
        else:
            remover(int(identifier), IPC_RMID, None)


class Privileges:
    """Args:
    runner: the uid of the Semaphore runner.
    proc: the proc filesystem the holders and IPC objects are read from.
    top: the directory the walk for files a uid left starts at.
    skipped: the directories that walk leaves out.
    """

    def __init__(self, runner, proc, top, skipped):
        self.runner = runner
        self.proc = proc
        self.top = top
        self.skipped = skipped

    def leftovers(self, uid):
        return owned(uid, self.top, self.skipped)

    def as_uid(self, uid, argv, group=None):
        return sandbox.dropped(uid, argv, group)

    def helper(self, uid, *argv, group=None):
        process = spawned(
            self.as_uid(
                uid, [sys.executable, *sandbox.ISOLATED, str(ENTRY), *argv], group
            ),
            env={"PATH": HELPER_PATH},
            stdin=subprocess.DEVNULL,
        )
        code = waited(process)
        if code != 0:
            raise sandbox.SandboxError(f"the {argv[0]} helper as {uid} ended {code}")

    def prepare(self, entries):
        for path, owner_uid, group, mode in entries:
            path.mkdir(mode=0o700)
            path.chmod(mode)
            os.chown(path, owner_uid, group)

    def start(self, uid, task, argv, environment, streams, files):
        """Args:
            uid: the uid of the sandbox.
            task: its task directory.
            argv: what runs in it.
            environment: its environment.
            streams: the stdin, stdout and stderr descriptors of the run.
            files: the task files the run names, checked for links as
                ``uid`` before ``argv`` starts.

        Returns:
            The :class:`subprocess.Popen` of the run, which execs ``argv``
            once ``setpriv`` dropped it to ``uid``.
        """
        reader, writer = os.pipe()
        plan = {"argv": argv, "env": environment, "cwd": str(task), "files": files}
        try:
            process = spawned(
                self.as_uid(
                    uid,
                    [
                        sys.executable,
                        *sandbox.ISOLATED,
                        str(ENTRY),
                        "exec",
                        str(reader),
                    ],
                ),
                env={"PATH": HELPER_PATH},
                stdin=streams[0],
                stdout=streams[1],
                stderr=streams[2],
                pass_fds=(reader,),
                umask=sandbox.UMASK,
                cwd="/",
                start_new_session=True,
            )
        finally:
            os.close(reader)
        with os.fdopen(writer, "w", encoding="utf-8") as handle:
            json.dump(plan, handle)
        return process

    def wait(self, process):
        return waited(process)

    def signal_all(self, uid, signum):
        self.helper(uid, "signal", str(int(signum)))

    def holders(self, uid):
        return holders(uid, self.proc)

    def ipc_left(self, uid):
        return sandbox.ipc_objects(uid, self.proc)

    def purge(self, uid, task, home):
        """Args:
            uid: the uid of a sandbox none of whose processes lives.
            task: its task directory.
            home: its ``HOME``.

        Raises:
            SandboxError: a file or a System V IPC object of the uid is left;
                every helper runs even when an earlier one failed.
        """
        failures = []
        for helper_uid, argv, group in (
            (uid, ("purge", str(task), str(home)), None),
            (uid, ("ipc",), None),
            (self.runner, ("purge", str(task)), uid),
        ):
            try:
                self.helper(helper_uid, *argv, group=group)
            except sandbox.SandboxError as failure:
                failures.append(failure)
        if failures:
            raise failures[0]
        for path in (task, home, task.parent):
            path.rmdir()
        left = self.ipc_left(uid)
        if left:
            raise sandbox.SandboxError(
                f"the sandbox {uid} keeps the IPC objects {left}"
            )
