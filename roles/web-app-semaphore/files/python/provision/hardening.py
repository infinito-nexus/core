from __future__ import annotations

import contextlib
import os
import pwd
import socket
import stat
from pathlib import Path

from provision import sandbox

PR_SET_NO_NEW_PRIVS = 38
OPEN_BITS = stat.S_IWOTH | stat.S_ISVTX
TMP_MODE = 0o700
SOCKET_MODE = 0o600
RUNNER_UID = "SEMAPHORE_SANDBOX_RUNNER_UID"
UID_BASE = "SEMAPHORE_SANDBOX_UID_BASE"
UID_COUNT = "SEMAPHORE_SANDBOX_UID_COUNT"
ROOT = "SEMAPHORE_SANDBOX_ROOT"
TMP = "SEMAPHORE_SANDBOX_TMP"
SHARED = "SEMAPHORE_SANDBOX_SHARED"
TOFU_BINARY = "SEMAPHORE_SANDBOX_TOFU"
CA_FILE = "SEMAPHORE_SANDBOX_CA"
BAO_ADDRESS = "SEMAPHORE_SANDBOX_BAO_ADDR"
BROKER_UID = "SEMAPHORE_SANDBOX_BROKER_UID"
BROKER_LOGIN = "SEMAPHORE_SANDBOX_BROKER_LOGIN"
LAYOUT = (
    RUNNER_UID,
    UID_BASE,
    UID_COUNT,
    ROOT,
    TMP,
    SHARED,
    TOFU_BINARY,
    BAO_ADDRESS,
    BROKER_UID,
    BROKER_LOGIN,
)


def no_new_privileges(libc):
    """Args:
        libc: the C library whose ``prctl`` sets ``PR_SET_NO_NEW_PRIVS``.

    Raises:
        SystemExit: the kernel refused it; swarm drops the service's
            ``no-new-privileges``, so the spawner sets it on itself.
    """
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise SystemExit("sandbox/spawner.py:the kernel refused no_new_privs")


def closed_mode(mode):
    """Args:
        mode: the mode of a directory any uid may create entries in.

    Returns:
        That mode without world-write and the sticky bit.
    """
    return stat.S_IMODE(mode) & ~OPEN_BITS


def world_writable(top, skipped):
    """Args:
        top: see :func:`sandbox.walked`.
        skipped: see :func:`sandbox.walked`.

    Returns:
        Every directory of :func:`sandbox.walked` whose mode lets any uid
        create an entry in it.
    """
    found = []
    for path in sandbox.walked(top, skipped):
        with contextlib.suppress(FileNotFoundError):
            if path.lstat().st_mode & stat.S_IWOTH:
                found.append(path)
    return found


def hidden(top, skipped):
    """Args:
        top: see :func:`sandbox.walked`.
        skipped: see :func:`sandbox.walked`.

    Returns:
        Every directory of :func:`sandbox.walked` that every uid may pass but
        the walker cannot list, so a world-writable directory below it
        escapes the walk.
    """
    found = []
    for path in sandbox.walked(top, skipped):
        try:
            if path.lstat().st_mode & stat.S_IXOTH:
                os.scandir(path).close()
        except PermissionError:
            found.append(path)
        except FileNotFoundError:
            continue
    return found


def close_open(top, root, tmp, shared):
    """Args:
        top: the directory the walk of the container starts at.
        root: the directory holding every sandbox, left out of the walk.
        tmp: the temporary directory of the runner, left out of the walk.
        shared: the world-writable directories the role declares, closed
            even where the walk misses them.

    Returns:
        The directories it closed to other uids.

    Raises:
        SystemExit: a directory keeps its world-write bit, so a sandbox uid
            could create files outside its own directories, or every uid may
            pass a directory the walk cannot list, so one could hide below.
    """
    unlisted = hidden(top, (root, tmp))
    if unlisted:
        raise SystemExit(
            f"sandbox/spawner.py:{unlisted[0]} lets every uid pass but hides "
            "what lies below it from the walk"
        )
    found = world_writable(top, (root, tmp))
    targets = sorted({*found, *(path for path in shared if path.is_dir())})
    for path in targets:
        try:
            path.chmod(closed_mode(path.lstat().st_mode))
            kept = path.lstat().st_mode & stat.S_IWOTH
            reason = "its mode keeps the world-write bit" if kept else ""
        except OSError as error:
            reason = error.strerror
        if reason:
            raise SystemExit(
                f"sandbox/spawner.py:{path} stays writable for every uid: {reason}"
            )
    return targets


def harden(runner, group, root, tmp, shared, top):
    """Args:
        runner: the uid of the Semaphore runner.
        group: its gid.
        root: the directory holding every sandbox.
        tmp: the temporary directory of the runner.
        shared: the world-writable directories the role declares.
        top: the directory :func:`close_open` walks.

    Returns:
        The listening socket of the spawner, bound in ``tmp`` before ``tmp``
        becomes a ``0700`` directory of the runner, so neither a sandbox uid
        nor any uid but the runner's reaches it. Root still owns each path
        when it changes its mode, as it holds no ``CAP_FOWNER``; a directory
        of another owner refuses the start.
    """
    close_open(top, root, tmp, shared)
    Path(root).chmod(sandbox.ROOT_MODE)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = sandbox.socket_path(tmp)
    path.unlink(missing_ok=True)
    listener.bind(str(path))
    path.chmod(SOCKET_MODE)
    os.chown(path, runner, group)
    tmp.chmod(TMP_MODE)
    os.chown(tmp, runner, group)
    listener.listen()
    return listener


def runner_environment(runner):
    account = pwd.getpwuid(runner)
    return os.environ | {
        "HOME": account.pw_dir,
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
    }


def layout(env):
    """Args:
        env: the environment of the spawner; the role sets every name of
            :data:`LAYOUT` in it.

    Returns:
        ``{"runner": uid, "uids": range, "root": path, "tmp": path,
        "shared": [path], "tofu": path, "ca": path or None, "bao": address,
        "broker": uid, "login": path}`` of the container;
        ``SEMAPHORE_SANDBOX_CA`` is empty unless the deploy trusts a
        self-signed CA. ``broker`` is the uid of the DNS broker, which alone
        reads ``login``, the file of its AppRole.

    Raises:
        SystemExit: a variable is missing or empty, the range holds root
            or the runner uid, or the broker uid is root, the runner's or
            one of the range.
    """
    missing = [name for name in LAYOUT if not env.get(name)]
    if missing:
        raise SystemExit(f"sandbox/spawner.py:the role sets no {', '.join(missing)}")
    try:
        runner, base, count, broker = (
            int(env[name]) for name in (RUNNER_UID, UID_BASE, UID_COUNT, BROKER_UID)
        )
    except ValueError:
        raise SystemExit(
            f"sandbox/spawner.py:{RUNNER_UID}, {UID_BASE}, {UID_COUNT} and "
            f"{BROKER_UID} name no uids"
        ) from None
    uids = range(base, base + count)
    if base <= 0 or count <= 0 or runner in uids:
        raise SystemExit("sandbox/spawner.py:the sandbox uids hold root or the runner")
    if broker <= 0 or broker == runner or broker in uids:
        raise SystemExit(
            "sandbox/spawner.py:the broker uid is root, the runner or a sandbox uid"
        )
    return {
        "runner": runner,
        "uids": uids,
        "root": Path(env[ROOT]),
        "tmp": Path(env[TMP]),
        "shared": [Path(path) for path in env[SHARED].split(":") if path],
        "tofu": Path(env[TOFU_BINARY]),
        "ca": Path(env[CA_FILE]) if env.get(CA_FILE) else None,
        "bao": env[BAO_ADDRESS],
        "broker": broker,
        "login": Path(env[BROKER_LOGIN]),
    }
