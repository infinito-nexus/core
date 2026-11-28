"""Args:
probe <token> <work> <tmp> [<task> ...]: runs as OpenTofu would, in a sandbox
    or outside one, starts a child in a session of its own and prints
    ``{"reads": [...], "child": pid}``: every read the sandbox must refuse that
    succeeded, by kind and path or pid, never a value.
check: as the runner uid in the provision runner, whose environment names the
    runner token and Semaphore's task directories, runs two probes at once,
    each in a sandbox of its own, then two outside any, and prints
    ``{"inside": [...], "outside": [...]}`` with ``exit`` and ``child_alive``
    of each.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# nocheck: project-root-import  the runner image starts this script by path with python3 -E -s, so only its own folder is on sys.path; the provision package lies one folder up in files/python
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from provision import sandbox

SCRIPT = Path(__file__).resolve()
MARKER = sandbox.PROBE_MARKER
IPC_PRIVATE = 0
IPC_CREAT = 0o1000
IPC_RMID = 0
SEGMENT_BYTES = 4096
SEGMENT_MODE = 0o600
MARKER_PREFIX = "sandbox-probe-"
SETTLE_SECONDS = 2
CHILD_SECONDS = 600
PROC = sandbox.PROC
ENROLMENT_FILE = "SEMAPHORE_RUNNER_TOKEN_FILE"
WORK = "SEMAPHORE_TMP_PATH"
PROBES = 2
READ_BYTES = 65536


def readable(path):
    try:
        with Path(path).open("rb") as handle:
            handle.read(1)
    except OSError:
        return False
    return True


def listable(path):
    try:
        os.listdir(path)
    except OSError:
        return False
    return True


def mem_readable(entry):
    """Args:
        entry: ``/proc/<pid>`` of a process.

    Returns:
        Whether one byte of its first readable mapping reads; a read at
        offset 0 of ``mem`` fails for every process, as nothing maps there.
    """
    try:
        maps = (entry / "maps").read_bytes().decode("utf-8", "replace")
        start = next(
            int(line.split("-", 1)[0], 16)
            for line in maps.splitlines()
            if line.split()[1].startswith("r")
        )
        with (entry / "mem").open("rb") as handle:
            handle.seek(start)
            return bool(handle.read(1))
    except (OSError, StopIteration, ValueError, IndexError):
        return False


def ipc_segment(libc):
    """Args:
        libc: the C library whose ``shmget`` creates a segment.

    Returns:
        The id of a new private System V shared memory segment, ``-1`` when
        none was created; it outlives the probe until it is removed.
    """
    return libc.shmget(IPC_PRIVATE, SEGMENT_BYTES, IPC_CREAT | SEGMENT_MODE)


def uid_of(entry):
    try:
        status = (entry / "status").read_bytes().decode("utf-8", "replace")
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("Uid:"):
            return int(line.split()[1])
    return None


def process_reads(own):
    """Args:
        own: the uid of the probe.

    Returns:
        ``environ``, ``mem``, ``fd`` or ``cwd`` with the pid of every process
        of another uid whose entry the probe opens.
    """
    reads = []
    for entry in PROC.iterdir():
        if not entry.name.isdigit() or uid_of(entry) in (own, None):
            continue
        checks = {
            "environ": lambda e=entry: readable(e / "environ"),
            "mem": lambda e=entry: mem_readable(e),
            "fd": lambda e=entry: listable(e / "fd"),
            "cwd": lambda e=entry: bool((e / "cwd").readlink()),
        }
        for kind, check in checks.items():
            with contextlib.suppress(OSError):
                if check():
                    reads.append(f"{kind} {entry.name}")
    return reads


def found_markers(own):
    """Args:
        own: the marker of this probe.

    Returns:
        Whether the environment of any process the probe reads holds the
        marker of another probe.
    """
    for entry in PROC.iterdir():
        try:
            raw = (entry / "environ").read_bytes()
        except OSError:
            continue
        for pair in raw.split(b"\0"):
            name, _, value = pair.decode("utf-8", "replace").partition("=")
            if name == MARKER and value.startswith(MARKER_PREFIX) and value != own:
                return True
    return False


def written(own_dirs, top):
    """Args:
        own_dirs: the task and temporary directories of the probe.
        top: the directory the walk starts at.

    Returns:
        Every directory below ``top`` outside ``own_dirs`` in which the probe
        creates a file.
    """
    writes = []
    for here in sandbox.walked(top, own_dirs):
        if not os.access(here, os.W_OK | os.X_OK):
            continue
        try:
            descriptor, path = tempfile.mkstemp(dir=here, prefix=MARKER_PREFIX)
        except OSError:
            continue
        os.close(descriptor)
        Path(path).unlink()
        writes.append(f"writes {here}")
    return writes


def probe(token, work, tmp, tasks):
    """Args:
        token: the runner token.
        work: Semaphore's task directories.
        tmp: the temporary directory of the runner, holding the lock
            directory of the provision runs.
        tasks: the task directories of every probe of the check.

    Returns:
        ``{"reads": [...], "child": pid}`` of this probe.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({CHILD_SECONDS})"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    time.sleep(SETTLE_SECONDS)
    cwd = Path.cwd()
    reads = ["token"] if readable(token) else []
    closed = (work, tmp, Path(tmp) / sandbox.LOCKS)
    reads += [f"closed {path}" for path in closed if listable(path)]
    reads += [f"task {task}" for task in tasks if Path(task) != cwd and listable(task)]
    reads += process_reads(os.getuid())
    if found_markers(os.environ.get(MARKER, "")):
        reads.append("marker")
    reads += written([cwd, Path(os.environ["HOME"])], sandbox.FILESYSTEM)
    time.sleep(SETTLE_SECONDS)
    return {
        "reads": reads,
        "child": child.pid,
        "child_mem": mem_readable(PROC / str(child.pid)),
        "segment": ipc_segment(ctypes.CDLL(None, use_errno=True)),
    }


def alive(pid):
    try:
        state = (PROC / str(pid) / "stat").read_bytes().decode("utf-8", "replace")
    except OSError:
        return False
    return state.rsplit(")", 1)[1].split()[0] != "Z"


def drained(reader):
    chunks = []
    while chunk := os.read(reader, READ_BYTES):
        chunks.append(chunk)
    os.close(reader)
    return json.loads(b"".join(chunks).decode("utf-8") or "{}")


def probe_arguments(tasks):
    return [
        os.environ[ENROLMENT_FILE],
        os.environ[WORK],
        tempfile.gettempdir(),
        *map(str, tasks),
    ]


def inside():
    """Returns:
    The reports of two probes that ran at once, each in a sandbox of its
    own, each with ``child_alive`` once its call ended and ``ipc_left``
    once its sandbox closed.
    """
    with sandbox.opened() as first, sandbox.opened() as second:
        tasks = [first, second]
        uids = [sandbox.of(task).uid for task in tasks]
        readers = []
        for task in tasks:
            home = str(sandbox.home_of(task))
            env = {
                "PATH": os.environ["PATH"],
                "HOME": home,
                "TMPDIR": home,
                MARKER: MARKER_PREFIX + secrets.token_hex(8),
            }
            reader, writer = os.pipe()
            sandbox.of(task).start(sandbox.PROBE, probe_arguments(tasks), env, writer)
            os.close(writer)
            readers.append(reader)
        reports = [drained(reader) for reader in readers]
        for task, report in zip(tasks, reports, strict=True):
            report["exit"] = sandbox.of(task).ended()
            report["child_alive"] = alive(report.get("child", 0))
    for uid, report in zip(uids, reports, strict=True):
        report["ipc_left"] = bool(sandbox.ipc_objects(uid, PROC))
    return reports


def outside():
    """Returns:
    The reports of two probes that ran at once as the runner uid, outside
    any sandbox; their children and segments are removed once seen.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    argv = [sys.executable, *sandbox.ISOLATED, str(SCRIPT), sandbox.PROBE]
    processes = [
        subprocess.Popen(
            [*argv, *probe_arguments([])],
            env={**os.environ, MARKER: MARKER_PREFIX + secrets.token_hex(8)},
            stdout=subprocess.PIPE,
        )
        for _ in range(PROBES)
    ]
    reports = []
    for process in processes:
        output, _ = process.communicate()
        report = json.loads(output.decode("utf-8") or "{}")
        report["exit"] = process.returncode
        report["child_alive"] = alive(report.get("child", 0))
        if report["child_alive"]:
            with contextlib.suppress(ProcessLookupError):
                os.kill(report["child"], signal.SIGKILL)
        held = sandbox.ipc_objects(os.getuid(), PROC)
        report["ipc_seen"] = ("shm", str(report.get("segment"))) in held
        if report["ipc_seen"]:
            libc.shmctl(int(report["segment"]), IPC_RMID, None)
        reports.append(report)
    return reports


def main(argv):
    """Args:
        argv: ``[script, mode, *arguments]``; see the module documentation.

    Returns:
        The exit code.
    """
    mode, arguments = argv[1], argv[2:]
    if mode == "probe":
        token, work, tmp, *tasks = arguments
        print(json.dumps(probe(token, work, tmp, tasks)))
        return 0
    if mode == "check":
        print(json.dumps({"inside": inside(), "outside": outside()}))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
