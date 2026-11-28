from __future__ import annotations

import contextlib
import json
import os
import socket
import stat
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.with_name("sandbox")
FILESYSTEM = Path("/")
PROC = Path("/proc")
KERNEL = (PROC, Path("/sys"))
SOCKET_NAME = "provision-sandbox.sock"
LOCKS = "provision-locks"
SOCKET_LIMIT = 108
TASK = "task"
HOME = "home"
ROOT_MODE = 0o711
RUN_MODE = 0o711
TASK_MODE = 0o2770
HOME_MODE = 0o700
FILE_MODE = 0o640
DIRECTORY_MODE = 0o750
UMASK = 0o007
SETPRIV = "setpriv"
ISOLATED = ("-E", "-s")
TOFU = "tofu"
PROBE = "probe"
PROBE_MARKER = "PROBE_MARKER"
PROBE_NAMES = frozenset({"PATH", "HOME", "TMPDIR", PROBE_MARKER})
PASSED = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "TZ",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
)
SYSVIPC = PROC / "sysvipc"
IPC_KINDS = {"shm": "shmid", "msg": "msqid", "sem": "semid"}
NOFOLLOW_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
NEW_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
STREAMS = 3
RECEIVE_BYTES = 65536
CLOSE_SECONDS = 60
OPEN_SECONDS = 60
QUEUED = {"queued": True}

_OPEN = {}


class SandboxError(Exception):
    """Args:
    message: why the spawner refused or broke off a sandbox, never a credential.
    """


def socket_path(directory):
    """Args:
        directory: the ``0700`` temporary directory of the Semaphore runner,
            which no sandbox uid reaches.

    Returns:
        The socket of the spawner in it.

    Raises:
        SandboxError: the path does not fit ``sun_path`` of ``AF_UNIX``.
    """
    path = Path(directory) / SOCKET_NAME
    if len(os.fsencode(path)) >= SOCKET_LIMIT:
        raise SandboxError(f"the socket path {path} exceeds {SOCKET_LIMIT - 1} bytes")
    return path


def walked(top, skipped):
    """Args:
        top: the directory the walk starts at.
        skipped: directories left out with everything below them, beside
            :data:`KERNEL`.

    Returns:
        ``top`` and every directory a listed directory below it names,
        without following a symbolic link, a directory the walk cannot list
        included; the spawner and the probe both walk the container through
        it.
    """
    left_out = {Path(path) for path in (*KERNEL, *skipped)}
    found = [Path(top)]
    for directory, names, _files in os.walk(top):
        here = Path(directory)
        names[:] = [
            name
            for name in names
            if here / name not in left_out and not (here / name).is_symlink()
        ]
        found += [here / name for name in names]
    return found


def task_relative(task, value):
    """Args:
        task: the task directory of a sandbox.
        value: a path a run names, absolute or relative to ``task``.

    Returns:
        The path relative to ``task``, ``None`` when it names no entry below
        it or names ``..``; root may not search the task directory, so only
        the sandbox uid checks it for links, see :func:`linked`.
    """
    path = Path(value)
    if path.is_absolute():
        if not path.is_relative_to(task):
            return None
        path = path.relative_to(task)
    if not path.parts or ".." in path.parts:
        return None
    return path


def linked(task, relative):
    """Args:
        task: the task directory, opened without following a link.
        relative: :func:`task_relative` of an entry below it.

    Returns:
        Whether a symbolic link, or an entry that is no directory, stands on
        the way to it or is the entry itself; the walk goes by directory
        descriptors and follows no link.
    """
    *directories, name = Path(relative).parts
    current = os.open(task, NOFOLLOW_DIRECTORY)
    try:
        for part in directories:
            try:
                inner = os.open(part, NOFOLLOW_DIRECTORY, dir_fd=current)
            except FileNotFoundError:
                return False
            except OSError:
                return True
            os.close(current)
            current = inner
        try:
            info = os.stat(name, dir_fd=current, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return stat.S_ISLNK(info.st_mode)
    finally:
        os.close(current)


def task_write(task, relative, text):
    """Args:
        task: the task directory of a sandbox.
        relative: the file below it; missing directories on the way are made.
        text: the new content.

    Returns:
        The path of the file. Each directory on the way is opened without
        following a symbolic link, the old entry of the file is removed and
        the file is created anew, so a link a plugin planted makes the write
        fail instead of landing in another run's directory.

    Raises:
        SandboxError: ``relative`` is absolute or names ``..``.
    """
    parts = Path(relative).parts
    if Path(relative).is_absolute() or ".." in parts or not parts:
        raise SandboxError(f"{relative} is no path below the task directory")
    *directories, name = parts
    current = os.open(task, NOFOLLOW_DIRECTORY)
    try:
        for part in directories:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, DIRECTORY_MODE, dir_fd=current)
            inner = os.open(part, NOFOLLOW_DIRECTORY, dir_fd=current)
            os.close(current)
            current = inner
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name, dir_fd=current)
        descriptor = os.open(name, NEW_FILE, FILE_MODE, dir_fd=current)
    finally:
        os.close(current)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), FILE_MODE)
        handle.write(text)
    return Path(task) / relative


def ipc_objects(uid, proc=PROC):
    """Args:
        uid: a sandbox uid.
        proc: the proc filesystem.

    Returns:
        ``[(kind, id)]`` of every System V shared memory segment, message
        queue and semaphore set whose owner or creator is ``uid``; each
        outlives every process of the uid until it is removed.
    """
    found = []
    for kind, column in IPC_KINDS.items():
        try:
            lines = (proc / "sysvipc" / kind).read_bytes().decode().splitlines()
        except OSError:
            continue
        header = lines[0].split() if lines else []
        for line in lines[1:]:
            fields = dict(zip(header, line.split(), strict=False))
            if str(uid) in (fields.get("uid"), fields.get("cuid")):
                found.append((kind, fields[column]))
    return found


def run_directory(root, uid):
    return Path(root) / str(uid)


def home_of(task):
    """Args:
        task: the task directory of a sandbox.

    Returns:
        The temporary directory and ``HOME`` of that sandbox, beside it.
    """
    return Path(task).with_name(HOME)


def layout(root, uid, runner):
    """Args:
        root: the directory holding every sandbox.
        uid: the uid and gid of the sandbox.
        runner: the uid of the Semaphore runner.

    Returns:
        ``[(path, owner, group, mode)]`` the spawner creates in that order: the
        run directory every uid passes but none lists, the task directory of
        the runner that the sandbox reaches through its group alone, and the
        temporary directory and ``HOME`` of the sandbox alone.
    """
    run = run_directory(root, uid)
    return [
        (run, 0, 0, RUN_MODE),
        (run / TASK, runner, uid, TASK_MODE),
        (run / HOME, uid, uid, HOME_MODE),
    ]


def dropped(uid, argv, group=None):
    """Args:
        uid: the uid and gid to run as.
        argv: what runs as that uid.
        group: the only supplementary group, ``uid`` for ``None``.

    Returns:
        The ``setpriv`` argv that drops every capability and privilege first.
    """
    return [
        SETPRIV,
        f"--reuid={uid}",
        f"--regid={uid}",
        f"--groups={uid if group is None else group}",
        "--inh-caps=-all",
        "--no-new-privs",
        "--",
        *argv,
    ]


class Channel:
    """Args:
    connection: a connected ``AF_UNIX`` stream socket; every message is one
        JSON line, and descriptors ride on the first byte of their line.
    """

    def __init__(self, connection):
        self.connection = connection
        self.buffer = b""
        self.descriptors = []

    def send(self, message, descriptors=()):
        data = json.dumps(message).encode("utf-8") + b"\n"
        sent = 0
        if descriptors:
            sent = socket.send_fds(self.connection, [data[:1]], list(descriptors))
        self.connection.sendall(data[sent:])

    def receive(self):
        """Returns:
        ``(message, descriptors)`` of the next line, ``(None, [])`` once the
        peer closed the connection.

        Raises:
            TimeoutError: the socket timeout passed first.
            ValueError: the line is no JSON; its descriptors are closed first.
        """
        while b"\n" not in self.buffer:
            data, descriptors, _flags, _address = socket.recv_fds(
                self.connection, RECEIVE_BYTES, STREAMS
            )
            self.descriptors.extend(descriptors)
            if not data:
                self.close_descriptors()
                return None, []
            self.buffer += data
        line, _, self.buffer = self.buffer.partition(b"\n")
        descriptors, self.descriptors = self.descriptors, []
        try:
            return json.loads(line), descriptors
        except BaseException:
            close_all(descriptors)
            raise

    def close_descriptors(self):
        close_all(self.descriptors)
        self.descriptors = []


def close_all(descriptors):
    for descriptor in descriptors:
        os.close(descriptor)


class Sandbox:
    """Args:
    channel: the :class:`Channel` to the spawner the sandbox lives on.
    uid: the uid of the sandbox.
    task: its task directory.
    """

    def __init__(self, channel, uid, task):
        self.channel = channel
        self.uid = uid
        self.task = task
        self.running = False

    def start(self, program, arguments, environment, stdout):
        """Args:
        program: :data:`TOFU` or :data:`PROBE`; the spawner adds its binary.
        arguments: the arguments of the program.
        environment: its environment, passed as it is; the spawner refuses a
            name the program does not take.
        stdout: the descriptor its stdout writes to; stdin is
            :data:`os.devnull` and stderr that of this process.
        """
        stdin = os.open(os.devnull, os.O_RDONLY)
        request = {
            "op": "run",
            "program": program,
            "argv": list(arguments),
            "env": dict(environment),
        }
        try:
            self.channel.send(request, [stdin, stdout, 2])
        finally:
            os.close(stdin)
        self.running = True

    def ended(self, timeout=None):
        """Args:
            timeout: the seconds to wait, ``None`` for no bound.

        Returns:
            The exit code of the run, negative for the signal that killed it,
            once no process of the sandbox lives, or ``None`` once the timeout
            passed first.
        """
        self.channel.connection.settimeout(timeout)
        try:
            message, _descriptors = self.channel.receive()
        except TimeoutError:
            return None
        finally:
            self.channel.connection.settimeout(None)
        self.running = False
        if message is None or "exit" not in message:
            raise self.broken((message or {}).get("error", "no reason"))
        return message["exit"]

    def broken(self, why):
        return SandboxError(f"the spawner broke off the sandbox {self.uid}: {why}")

    def signal(self, signum):
        self.channel.send({"op": "signal", "signal": int(signum)})

    def kill(self):
        """Returns:
        The exit code once the spawner killed every process of the sandbox,
        ``None`` when nothing ran.
        """
        if not self.running:
            return None
        self.channel.send({"op": "kill"})
        return self.ended(CLOSE_SECONDS)

    def close(self):
        """Raises:
        SandboxError: the spawner kept the sandbox, broke it off or broke the
            connection off, an ``OSError`` of the kill, the close or its
            answer among them.
        """
        try:
            self.kill()
            self.channel.send({"op": "close"})
            self.channel.connection.settimeout(CLOSE_SECONDS)
            closed, _descriptors = self.channel.receive()
        except OSError as failure:
            raise self.broken(failure) from None
        if closed != {"closed": True}:
            raise SandboxError(f"the spawner kept the sandbox {self.uid}")


def of(task):
    """Args:
        task: the task directory a run got from :func:`opened`.

    Returns:
        The :class:`Sandbox` of that run.

    Raises:
        SandboxError: the directory belongs to no open sandbox, so nothing
            runs for it.
    """
    try:
        return _OPEN[str(task)]
    except KeyError:
        raise SandboxError(f"{task} is the task directory of no sandbox") from None


@contextlib.contextmanager
def opened():
    """Returns:
    The task directory of a sandbox the spawner opens for one run under a
    uid of its own; the spawner kills every process of it, removes its files
    and frees the uid once the block ends or this process dies;
    :class:`SandboxError` once the spawner is unreachable, queued no open
    within :data:`OPEN_SECONDS`, the wait for a uid unbounded, or broke it or
    its connection off, unless the block raised first, whose error stays.
    """
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(OPEN_SECONDS)
        channel = Channel(connection)
        try:
            connection.connect(str(socket_path(tempfile.gettempdir())))
            channel.send({"op": "open"})
            queued, _descriptors = channel.receive()
            connection.settimeout(None)
            message = channel.receive()[0] if queued == QUEUED else queued
        except TimeoutError:
            raise SandboxError(
                f"the spawner opened no sandbox within {OPEN_SECONDS} seconds"
            ) from None
        except OSError as failure:
            raise SandboxError(f"the spawner opened no sandbox: {failure}") from None
        if message is None or "task" not in message:
            raise SandboxError(f"the spawner opened no sandbox: {message}")
        task = Path(message["task"])
        box = Sandbox(channel, message["uid"], task)
        _OPEN[str(task)] = box
        try:
            yield task
        except BaseException:
            with contextlib.suppress(SandboxError):
                box.close()
            raise
        finally:
            del _OPEN[str(task)]
        box.close()
    finally:
        connection.close()
