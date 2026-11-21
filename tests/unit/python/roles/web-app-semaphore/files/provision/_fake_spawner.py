from __future__ import annotations

import contextlib
import os
import signal
import socket
import threading
from pathlib import Path

FAKE_UIDS = range(1, 257)
JOIN_SECONDS = 30


def environment_of(pid):
    """Args:
        pid: a process id.

    Returns:
        Its environment, ``{}`` for a zombie, one of another uid or one that
        ended.
    """
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()  # nocheck: cache-read proc
    except OSError:
        return {}
    pairs = (entry.decode("utf-8", "replace") for entry in raw.split(b"\0") if entry)
    return dict(pair.split("=", 1) for pair in pairs if "=" in pair)


def state_of(pid):
    """Args:
        pid: a process id.

    Returns:
        ``(state, process group, session)`` from ``/proc/<pid>/stat``,
        ``None`` once it ended.
    """
    try:
        stat_file = Path(f"/proc/{pid}/stat")
        raw = stat_file.read_bytes()  # nocheck: cache-read proc
        text = raw.decode("utf-8", "replace")
    except OSError:
        return None
    fields = text.rsplit(")", 1)[1].split()
    return fields[0], int(fields[2]), int(fields[3])


def living(pid):
    state = state_of(pid)
    return state is not None and state[0] != "Z"


def process_ids():
    entries = Path("/proc").iterdir()
    return [int(entry.name) for entry in entries if entry.name.isdigit()]


def inode(descriptor):
    info = os.fstat(descriptor)
    return info.st_dev, info.st_ino


def held(pipe, writer):
    """Args:
        pipe: :func:`inode` of a pipe.
        writer: the write end the test keeps open.

    Returns:
        Every other descriptor of this process that holds the pipe.
    """
    found = []
    for name in os.listdir("/proc/self/fd"):
        with contextlib.suppress(OSError):
            if int(name) != writer and inode(int(name)) == pipe:
                found.append(int(name))
    return found


def fake_privileges(spawner, root, extra):
    """Args:
        spawner: the loaded ``sandbox.spawner`` module.
        root: the directory of the sandboxes.
        extra: environment values every run gets after the spawner admitted
            it, the settings of a fake ``tofu`` the session never passes.

    Returns:
        A :class:`spawner.privileged.Privileges` that runs every sandbox and helper as
        the uid of the test, so its real purge removes every file of a run.
        Without root no uid of its own marks a sandbox's processes, so it
        tells them by the ``HOME`` the session gives each sandbox, which a
        child in a new session keeps; ``sandbox/test_spawner.py`` proves the
        kill by uid on a fake kernel, the live probe on the real one. The
        ``ipc`` helper never runs, as it would remove the System V objects of
        the test's own uid, and ``root`` stands in for ``/proc``, so no IPC
        table of the host is read.
    """

    class FakePrivileges(spawner.privileged.Privileges):
        def __init__(self):
            super().__init__(os.getuid(), root, root, ())

        def as_uid(self, uid, argv, group=None):
            return list(argv)

        def helper(self, uid, *argv, group=None):
            if argv[0] != "ipc":
                super().helper(uid, *argv, group=group)

        def prepare(self, entries):
            for path, _owner, _group, mode in entries:
                path.mkdir(mode=0o700)
                path.chmod(mode)

        def start(self, uid, task, argv, environment, streams, files):
            return super().start(uid, task, argv, environment | extra, streams, files)

        def holders(self, uid):
            home = str(spawner.sandbox.run_directory(root, uid) / spawner.sandbox.HOME)
            return [
                pid for pid in process_ids() if environment_of(pid).get("HOME") == home
            ]

        def signal_all(self, uid, signum):
            for pid in self.holders(uid):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(pid, signum)

    return FakePrivileges()


class FakeSpawner:
    """Args:
    spawner: the loaded ``sandbox.spawner`` module.
    root: the directory of the sandboxes, created ``0711``.
    tmp: the ``TMPDIR`` whose socket it serves.
    tofu: the fake ``tofu`` every run starts.
    cli_config: the ``TF_CLI_CONFIG_FILE`` a run may pass; ``self.pinned``
        holds it with the other pinned values, without a CA as in the default
        TLS mode, and takes the ``BAO_ADDR`` of a harness's fake OpenBao.
    requester: the file each open writes the pid of its peer to, ``None``
        for none.
    """

    def __init__(self, spawner, root, tmp, tofu, cli_config, requester=None):
        root = Path(root)
        root.mkdir(mode=0o711, exist_ok=True)
        root.chmod(0o711)
        self.root = root
        self.extra = {}
        self.privileges = fake_privileges(spawner, root, self.extra)
        admission = spawner.admission
        self.pinned = admission.pinned_values(os.environ, cli_config, None, None)
        known = admission.programs(tofu, admission.credentials(), self.pinned)

        class Recording(spawner.Spawner):
            def serve(self, connection):
                if requester is not None:
                    pid, _uid, _gid = spawner.PEERCRED.unpack(
                        connection.getsockopt(
                            socket.SOL_SOCKET,
                            socket.SO_PEERCRED,
                            spawner.PEERCRED.size,
                        )
                    )
                    Path(requester).write_text(str(pid), encoding="utf-8")
                super().serve(connection)

        self.spawner = Recording(self.privileges, root, FAKE_UIDS, known)
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(spawner.sandbox.socket_path(tmp)))
        self.listener.listen()
        self.served = []
        self.accepting = threading.Thread(target=self.accept, daemon=True)
        self.accepting.start()

    def accept(self):
        while True:
            try:
                connection, _address = self.listener.accept()
            except OSError:
                return
            thread = threading.Thread(
                target=self.spawner.serve, args=(connection,), daemon=True
            )
            thread.start()
            self.served.append(thread)

    def close(self):
        with contextlib.suppress(OSError):
            self.listener.shutdown(socket.SHUT_RDWR)
        self.listener.close()
        self.accepting.join(JOIN_SECONDS)
        for thread in self.served:
            thread.join(JOIN_SECONDS)
        for uid in sorted(self.spawner.active):
            self.privileges.signal_all(uid, signal.SIGKILL)
