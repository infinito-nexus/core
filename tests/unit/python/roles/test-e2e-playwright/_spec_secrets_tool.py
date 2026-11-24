from __future__ import annotations

import contextlib
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ._spec_secrets_fakes import (
    MASKER,
    NAME,
    VALUE,
    caller_env,
    container_argv,
    install,
    make_run,
    scratch_text,
    state_of,
)

PIDFILE = f"{NAME}.pid"

FAKE_DOCKER = """\
import os, pathlib, signal, subprocess, sys, time
probe = pathlib.Path(sys.argv[0]).parent.with_name("probe")
switched = lambda name: (probe / name).exists()
args = sys.argv[1:]
with (probe / "calls").open("a") as log:
    log.write(args[0] + "\\n")
def pid(name):
    try:
        found = int((probe / f"{name}.pid").read_text())
        state = pathlib.Path(f"/proc/{found}/stat").read_text()
    except (OSError, ValueError):
        return None
    return found if state.rsplit(") ", 1)[1][:1] != "Z" else None
def kill(name):
    os.kill(pid(name), signal.SIGKILL)
    for _ in range(100):
        if not pid(name):
            break
        time.sleep(0.05)
doom = probe / f"{args[-1]}.doom"
if args[0] == "inspect":
    if pid(args[-1]) and doom.exists() and float(doom.read_text()) <= time.time():
        kill(args[-1])
    sys.exit(0 if pid(args[-1]) else f"Error: No such object: {args[-1]}")
if args[0] == "rm":
    if not pid(args[-1]):
        sys.exit(f"Error response from daemon: No such container: {args[-1]}")
    if switched("STUCK"):
        sys.exit(f"Error response from daemon: cannot remove container {args[-1]}")
    if switched("SLOW"):
        if not doom.exists():
            doom.write_text(str(time.time() + 2.5))
        sys.exit(f"Error response from daemon: removal of {args[-1]} is already in progress")
    kill(args[-1])
    print(args[-1])
    sys.exit(0)
name = args[args.index("--name") + 1]
cidfile = next((a.split("=", 1)[1] for a in args if a.startswith("--cidfile=")), "")
reports = next(a for a in args if a.endswith(":/reports")).rsplit(":", 1)[0]
mount = next(a for a in args if a.startswith("type=bind,src=")).split(",")[1][4:]
value = pathlib.Path(mount, "LONG_KEY").read_text()
(probe / "argv.json").write_text(__import__("json").dumps(args))
for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(signum, signal.SIG_IGN)
(probe / "masker.pid").write_text(str(os.getppid()))
pid1 = pathlib.Path(__file__).with_name("pid1.py")
detached = subprocess.DEVNULL if switched("DETACH") else None
container = subprocess.Popen(
    [sys.executable, str(pid1), str(probe / f"{name}.pid"), cidfile, name, reports, value],
    start_new_session=True,
    stdout=detached,
    stderr=detached,
)
if detached is not None:
    for _ in range(200):
        if pathlib.Path(reports, "playwright-junit.xml").exists():
            break
        time.sleep(0.05)
    sys.exit(0)
code = container.wait()
sys.exit(128 - code if code < 0 else code)
"""
PID1 = """\
import contextlib, os, pathlib, sys, time
pidfile, cidfile, name, reports, value = sys.argv[1:6]
pathlib.Path(pidfile).write_text(str(os.getpid()))
if pathlib.Path(pidfile).with_name("LATE_CID").exists():
    time.sleep(1.0)
if cidfile:
    pathlib.Path(cidfile).write_text(name)
for turn in range(600):
    with contextlib.suppress(OSError):
        pathlib.Path(reports, "junit.part").write_text(f"<failure>{value}</failure>")
        pathlib.Path(reports, "junit.part").replace(pathlib.Path(reports, "playwright-junit.xml"))
    if not turn:
        print("started", flush=True)
    time.sleep(0.1)
"""


def ready(proc: subprocess.Popen, seconds: float) -> bool:
    """Wait for the fake container's first line or its end, bounded.

    Args:
        proc: the masker, its stdout a pipe.
        seconds: the longest to wait.

    Returns:
        Whether it printed a whole line in time; the pipe is read as it
        fills, so a partial line that stays never blocks past the deadline.
    """
    deadline, seen = time.monotonic() + seconds, b""
    while b"\n" not in seen:
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        readable, _, _ = select.select([proc.stdout], [], [], left)
        if not readable:
            return False
        chunk = os.read(proc.stdout.fileno(), 4096)
        if not chunk:
            return False
        seen += chunk
    return True


def reap(pidfile: Path) -> bool:
    """Kill the fake container a pid file names, if it still runs.

    Args:
        pidfile: the file the container wrote its pid to; a missing one
            means no container started.

    Returns:
        Whether it was still running; a zombie counts as gone.
    """
    if not pidfile.exists():
        return False
    pid = int(scratch_text(pidfile))
    try:
        state = scratch_text(Path(f"/proc/{pid}/stat")).rsplit(") ", 1)[1][:1]
    except OSError:
        return False
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    return state != "Z"


def fake_tool(root: Path, directory: Path) -> list[str]:
    """Install the fake container tool, which behaves like the engine, into ``bin``.

    Args:
        root: the scratch dir holding ``bin``.
        directory: the run directory the container mounts and reports into.

    Returns:
        ``container_argv`` for a container named ``NAME``, the tool found
        as ``docker`` on the PATH ``tool_env`` sets; ``rm --force`` of a
        missing container fails with ``No such container``.
    """
    (root / "bin" / "pid1.py").write_text(PID1, encoding="utf-8")
    docker = root / "bin" / "docker"
    docker.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}", encoding="utf-8")
    docker.chmod(0o755)
    return container_argv(root, directory)


def tool_env(
    probe: Path,
    stuck: bool,
    detach: bool = False,
    slow: bool = False,
    late: bool = False,
) -> dict[str, str]:
    """Switch the fake container tool through files in its probe dir, then build its PATH.

    Args:
        probe: where it keeps its pid files and reads its switches, which
            survive the ``container_env`` the masker hands it; its parent
            holds ``bin``.
        stuck: whether its ``rm`` fails to remove a running container.
        detach: whether its ``run`` returns while the container keeps going.
        slow: whether its ``rm`` reports a removal in progress, which only
            ends 2.5 seconds after the first ``rm``.
        late: whether the container writes its ``CID`` only a second after
            it started.

    Returns:
        ``caller_env`` with ``bin`` first on PATH.
    """
    switches = {"STUCK": stuck, "DETACH": detach, "SLOW": slow, "LATE_CID": late}
    for name, on in switches.items():
        (probe / name).unlink(missing_ok=True)
        if on:
            (probe / name).touch()
    return {
        **caller_env(),
        "PATH": f"{probe.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
    }


def detached_run(stuck: bool, *replacements, slow: bool = False) -> list[str]:
    """Mask a run whose tool returns while its container keeps writing reports.

    Args:
        stuck: whether the fake tool's ``rm`` fails to remove the container.
        *replacements: changes to the masker or matcher, for a negative control.
        slow: whether the removal takes 2.5 seconds, longer than three tries
            a second apart wait.

    Returns:
        The masker's exit code, what the reports dir showed after it and
        whether the container outlived it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, *replacements)
        directory = make_run(helper, f"LONG_KEY={VALUE}\n")
        reports, probe = root / "reports", root / "probe"
        reports.mkdir()
        probe.mkdir()
        run = fake_tool(root, directory)
        masker = [sys.executable, str(root / "bin" / MASKER.name), "mask"]
        try:
            done = subprocess.run(
                [*masker, str(directory), str(reports), "--", *run, "--"],
                capture_output=True,
                check=False,
                env=tool_env(probe, stuck, detach=True, slow=slow),
                timeout=60,
            )
            return [
                f"masker {done.returncode}",
                f"published {state_of(reports / 'playwright-junit.xml')}",
                f"container alive {reap(probe / PIDFILE)}",
            ]
        finally:
            reap(probe / PIDFILE)


def stopped_run(how: signal.Signals, stuck: bool = False, *replacements) -> list[str]:
    """Stop a masker whose container survives it, then scrub with the tool.

    Args:
        how: TERM, which the masker answers, or KILL, which it cannot.
        stuck: whether the fake tool's ``rm`` fails to remove the container.
        *replacements: changes to the masker or matcher, for a negative control.

    Returns:
        In order: the masker's exit code, what the reports dir showed right
        after, the scrub's exit code, whether the container outlived the
        scrub, what the reports dir showed after the scrub: ``none``,
        ``masked`` or ``leaks``, and how often the masker called ``rm``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, *replacements)
        directory = make_run(helper, f"LONG_KEY={VALUE}\n")
        reports, probe = root / "reports", root / "probe"
        reports.mkdir()
        probe.mkdir()
        run = fake_tool(root, directory)
        env = tool_env(probe, stuck)
        masker = [sys.executable, str(root / "bin" / MASKER.name)]
        proc = subprocess.Popen(
            [*masker, "mask", str(directory), str(reports), "--", *run, "--"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
        try:
            if not ready(proc, 20):
                return ["the fake container never started"]
            os.killpg(proc.pid, how)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            time.sleep(0.3)
            junit = reports / "playwright-junit.xml"
            events = [f"masker {proc.returncode}", f"published {state_of(junit)}"]
            removals = scratch_text(probe / "calls").split().count("rm")
            scrub = [*masker, "scrub", str(directory), str(reports), run[0]]
            done = subprocess.run(scrub, capture_output=True, check=False, env=env)
            time.sleep(0.5)
            events.append(f"scrub {done.returncode}")
            events.append(f"container alive {reap(probe / PIDFILE)}")
            events.append(f"published {state_of(junit)}")
            events.append(f"masker removals {removals}")
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            proc.stdout.close()
            reap(probe / PIDFILE)
        return events


def late_cid_run(*replacements) -> list[str]:
    """TERM the masker before its container wrote ``CID``, then let the run end.

    Args:
        *replacements: changes to the masker or matcher, for a negative control.

    Returns:
        The masker's exit code and whether the container, which writes
        ``CID`` a second after it started, outlived the masker.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = install(root / "bin", root, *replacements)
        directory = make_run(helper, f"LONG_KEY={VALUE}\n")
        reports, probe = root / "reports", root / "probe"
        reports.mkdir()
        probe.mkdir()
        run = fake_tool(root, directory)
        masker = [sys.executable, str(root / "bin" / MASKER.name), "mask"]
        proc = subprocess.Popen(
            [*masker, str(directory), str(reports), "--", *run, "--"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=tool_env(probe, False, detach=True, late=True),
        )
        try:
            for _ in range(200):
                if (probe / "masker.pid").exists() or proc.poll() is not None:
                    break
                time.sleep(0.05)
            if (directory / ".cid").exists() or proc.poll() is not None:
                return ["the masker was not stopped before the container id"]
            proc.send_signal(signal.SIGTERM)
            code = proc.wait(timeout=60)
            return [f"masker {code}", f"container alive {reap(probe / PIDFILE)}"]
        finally:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            proc.wait()
            reap(probe / PIDFILE)
