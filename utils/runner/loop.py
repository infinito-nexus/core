from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from utils.runner import POOL_RUNNER_KEY, jobs

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import TextIO

    Run = Callable[..., subprocess.CompletedProcess]
    Teardown = Callable[[str], Sequence[str]]

ENTRY = Path("scripts") / "tests" / "deploy" / "job" / "entry.sh"
GIT = ".git"
GITDIR = "gitdir:"
CUSTOM_ENV = "custom.env"
NEVER_LISTED = (".env", CUSTOM_ENV)
MANIFEST = "checkout.files"
PRIVATE = 0o600
LISTING = ("git", "ls-files", "-z", "--cached", "--others", "--exclude-standard")
POOL_SETTINGS = {POOL_RUNNER_KEY: "true", "INFINITO_DEPLOY_VIA_POOL": "false"}
WIPE_MOUNT = "/install"
STACK_KEY = "INFINITO_STACK_NAME"
ROOTS_KEY = "INFINITO_RUNNER_WORKTREE_ROOTS"
INSTALL_KEY = "INFINITO_RUNNER_INSTALL_DIR"
CHECKOUT_KEY = "INFINITO_RUNNER_CHECKOUT"
IMAGE_KEY = "INFINITO_RUNNER_IMAGE"
RUNNER_ONLY = (
    "PYTHONPATH",
    "RUNNER_SRC_DIR",
    "INFINITO_RUNNER_QUEUE_DIR",
    ROOTS_KEY,
    INSTALL_KEY,
    CHECKOUT_KEY,
    IMAGE_KEY,
)
REFUSED = 126
UNSTARTABLE = 127
ABANDONED = 137
FAILED_POLL = 60.0


class StaleCopyError(OSError):
    pass


@dataclasses.dataclass(frozen=True)
class Runner:
    """Args:
    name: the runner's name, also the compose project of its job stack.
    roots: the worktree roots it mounts; a job's checkout must resolve below one.
    install: its own install directory, ``RUNNER_INSTALL_DIR/<N>``.
    checkout: the directory below ``install`` every job's checkout is
        copied into and runs from.
    image: the toolchain image the runner runs, which removes the copy of
        the job before as root.
    env: its environment, which carries its per-instance DinD values.
    """

    name: str
    roots: tuple[Path, ...]
    install: Path
    checkout: Path
    image: str
    env: Mapping[str, str]


def job_env(runner: Runner) -> dict[str, str]:
    """Args:
        runner: the runner that runs the job.

    Returns:
        The runner's environment without the keys only its own loop reads,
        such as the ``PYTHONPATH`` of the checkout the loop runs from, with
        ``INFINITO_STACK_NAME`` set to the runner's job stack, no bytecode
        written into the copy, and :data:`POOL_SETTINGS`, so the job uses the
        infra runner's caches but neither starts nor attaches to an infra
        runner itself and submits no pool job.
    """
    kept = {key: value for key, value in runner.env.items() if key not in RUNNER_ONLY}
    return {
        **kept,
        **POOL_SETTINGS,
        STACK_KEY: runner.name,
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _within(path: Path | str, parent: Path | str) -> bool:
    return Path(os.path.realpath(path)).is_relative_to(os.path.realpath(parent))


def _below(path: Path | str, parent: Path | str) -> bool:
    return _within(path, parent) and os.path.realpath(path) != os.path.realpath(parent)


def confined(checkout: str, roots: Sequence[Path]) -> Path | None:
    """Args:
        checkout: a job's checkout as its record names it.
        roots: the worktree roots the runner mounts.

    Returns:
        The checkout with every link resolved, None when it is no absolute
        path, resolves outside every root or to a root itself, or holds no
        job entry.
    """
    if not Path(checkout).is_absolute() or "\0" in checkout:
        return None
    real = Path(os.path.realpath(checkout))
    inside = any(_below(real, root) for root in roots)
    return real if inside and (real / ENTRY).is_file() else None


def _own(target: Path, install: Path) -> Path:
    if not _within(target.parent, install):
        raise OSError(f"{target.parent} resolves outside {install}")
    if target.is_symlink():
        target.unlink()
    target.mkdir(exist_ok=True)
    return target


def wipe_command(runner: Runner) -> list[str]:
    """Args:
        runner: a runner whose copy of the job before goes.

    Returns:
        The throwaway container of the runner's own image that removes the
        copy as root, so files a job's root container wrote into it go too.
        It mounts the install directory alone, without network, and removes
        its one folder of the copy, a link there as a link.
    """
    return [
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--user",
        "0:0",
        "--entrypoint",
        "rm",
        "--volume",
        f"{runner.install}:{WIPE_MOUNT}",
        runner.image,
        "-rf",
        "--one-file-system",
        "--",
        f"{WIPE_MOUNT}/{runner.checkout.name}",
    ]


def clear_copy(runner: Runner, run: Run) -> None:
    """Args:
        runner: the runner whose copy of the job before goes.
        run: runs a command like :func:`subprocess.run`.

    Raises:
        StaleCopyError: the removal as root failed or did not start, or the
            empty copy cannot be made again inside the install directory.
    """
    try:
        done = run(wipe_command(runner), capture_output=True, text=True, check=False)
    except OSError as exc:
        raise StaleCopyError(f"rm as root did not start: {exc}") from exc
    if done.returncode != 0:
        raise StaleCopyError(
            f"rm as root in {runner.image} failed (rc={done.returncode}): "
            f"{(done.stderr or '').strip()}"
        )
    try:
        _own(runner.checkout, runner.install)
    except OSError as exc:
        raise StaleCopyError(str(exc)) from exc


def _gitdir(checkout: Path) -> Path:
    dot = checkout / GIT
    if dot.is_dir() and not dot.is_symlink():
        return Path(os.path.realpath(dot))
    with dot.open(encoding="utf-8") as handle:
        line = handle.readline().strip()
    if not line.startswith(GITDIR):
        raise OSError(f"{dot} names no {GITDIR}")
    gitdir = Path(os.path.realpath(checkout / line.removeprefix(GITDIR).strip()))
    if not gitdir.is_dir():
        raise OSError(f"{dot} points to {gitdir}, which this runner does not mount")
    return gitdir


def _place(source: Path, destination: Path, target: Path) -> None:
    if not _within(destination.parent, target):
        raise OSError(f"{destination.parent} resolves outside {target}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_dir() and not destination.is_symlink():
        destination.rmdir()
    elif destination.is_symlink() or destination.exists():
        destination.unlink()
    if source.is_symlink():
        destination.symlink_to(source.readlink())
    else:
        shutil.copy2(source, destination)


def _listed(checkout: Path) -> list[str]:
    listed = subprocess.run(LISTING, cwd=checkout, capture_output=True, check=True)
    names = (os.fsdecode(raw) for raw in listed.stdout.split(b"\0") if raw)
    return [
        name
        for name in names
        if name not in NEVER_LISTED
        and ((checkout / name).is_symlink() or (checkout / name).is_file())
    ]


def _manifest(install: Path) -> set[str]:
    path = install / MANIFEST
    if path.is_symlink() or not path.is_file():
        return set()
    with path.open(encoding="utf-8") as handle:
        return {name for name in handle.read().split("\0") if name}


def _replace(path: Path, text: str) -> None:
    if path.is_symlink() or path.exists():
        path.unlink()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, PRIVATE), "w", encoding="utf-8") as handle:
        handle.write(text)


def _drop(target: Path, name: str) -> None:
    path = target / name
    if _within(path.parent, target) and (path.is_symlink() or path.is_file()):
        path.unlink()


def _custom_env(checkout: Path, target: Path) -> None:
    source = checkout / CUSTOM_ENV
    kept: list[str] = []
    if source.is_file() and not source.is_symlink():
        with source.open(encoding="utf-8") as handle:
            kept = [
                line.rstrip("\n")
                for line in handle
                if line.removeprefix("export ").split("=", 1)[0].strip()
                not in POOL_SETTINGS
            ]
    pinned = [f"{key}={value}" for key, value in POOL_SETTINGS.items()]
    _replace(target / CUSTOM_ENV, "\n".join([*kept, *pinned]) + "\n")


def copy_checkout(checkout: Path, target: Path, install: Path) -> Path:
    """Args:
        checkout: the job's checkout, resolved inside the worktree roots.
        target: the runner's own directory the job runs from.
        install: the runner's install directory, which must hold the target
            and keeps the list of files copied last.

    Returns:
        The target mirroring every file git sees in the checkout, tracked or
        untracked and not ignored, links kept as links, never ``.env``: a
        file copied before that git no longer lists goes, while files the
        job wrote itself stay. Beside them its ``custom.env``, the
        checkout's own with :data:`POOL_SETTINGS` pinned and mode 0600 like
        every file the runner writes itself, and a ``.git`` file
        naming the checkout's git directory as the runner mounts it, so
        ``git rev-parse`` works in the copy while the worktree stays a
        read-only mount.

    Raises:
        OSError: the target lies outside the install directory, the
            checkout's git directory is not mounted, or a file cannot be read
            or written.
        subprocess.CalledProcessError: git cannot list the checkout.
    """
    gitdir = _gitdir(checkout)
    names = _listed(checkout)
    _own(target, install)
    for name in sorted(_manifest(install) - set(names)):
        _drop(target, name)
    for name in names:
        _place(checkout / name, target / name, target)
    _custom_env(checkout, target)
    _replace(target / GIT, f"{GITDIR} {gitdir}\n")
    _replace(install / MANIFEST, "\0".join(names))
    return target


def job_command(checkout: Path, record: jobs.Job) -> list[str]:
    """Args:
        checkout: the copy of the job's checkout the job runs from.
        record: a claimed job.

    Returns:
        The job entry of that checkout running ``make <target> <args>``.
    """
    return [str(checkout / ENTRY), "make", record.target, *record.args]


def _note(handle: TextIO, text: str) -> None:
    handle.write(f"[runner] {text}\n")
    handle.flush()


def _deploy(
    record: jobs.Job, runner: Runner, run: Run, handle: TextIO
) -> tuple[int, bool]:
    checkout = confined(record.checkout, runner.roots)
    if checkout is None:
        roots = ", ".join(str(root) for root in runner.roots)
        _note(
            handle,
            f"job {record.id} refused: its checkout {record.checkout!r} is relative, "
            f"resolves outside the worktree roots {roots} of {runner.name} or to "
            f"one of them, or holds no {ENTRY}",
        )
        return REFUSED, False
    clear_copy(runner, run)
    try:
        copy = copy_checkout(checkout, runner.checkout, runner.install)
        done = run(
            job_command(copy, record),
            cwd=str(copy),
            env=job_env(runner),
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        _note(handle, f"job {record.id} did not start: {exc}")
        return UNSTARTABLE, False
    return done.returncode, True


def stale_copy(runner: Runner, reason: object) -> str:
    """Args:
        runner: a runner whose copy of the job before cannot be removed.
        reason: why the removal failed.

    Returns:
        The line that marks the runner failed: the path to remove inside the
        infra runner, and that the runner takes no job until it is gone.
    """
    return (
        f"{runner.name} cannot remove the copy {runner.checkout} the job before "
        f"left ({reason}); remove it inside the infra runner, {runner.name} "
        "takes no job until then"
    )


def _removed(
    root: Path, runner: Runner, run: Run, teardown: Teardown, handle: TextIO
) -> bool:
    try:
        code = run(
            list(teardown(runner.name)),
            cwd=str(root),
            env=dict(runner.env),
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        ).returncode
    except OSError as exc:
        _note(handle, f"removing stack {runner.name} did not start: {exc}")
        return False
    if code != 0:
        _note(handle, f"removing stack {runner.name} failed (rc={code})")
    return code == 0


def _close(
    root: Path,
    record: jobs.Job,
    runner: Runner,
    code: int,
    run: Run,
    clock: Callable[[], float],
    teardown: Teardown,
    handle: TextIO,
) -> jobs.Job:
    if record.hold or _removed(root, runner, run, teardown, handle):
        return jobs.finish(root, record.id, code, clock())
    _note(
        handle,
        f"job {record.id} stays held on {runner.name} while its stack exists; "
        + jobs.RELEASE.format(id=record.id)
        + " removes it",
    )
    return jobs.strand(root, record.id, code, clock())


def run_job(
    root: Path,
    record: jobs.Job,
    runner: Runner,
    run: Run,
    clock: Callable[[], float],
    teardown: Teardown,
) -> jobs.Job | None:
    """Args:
        root: the queue directory.
        record: the job this runner claimed.
        runner: this runner.
        run: runs a command like :func:`subprocess.run`.
        clock: returns the current time.
        teardown: the command that removes a job stack, by its compose project name.

    Returns:
        The finished job: held with its stack kept when it was submitted with
        hold, else done or failed by its exit status after the runner's own
        stack is gone, and held while a failed removal leaves that stack.
        A relative checkout, one outside the worktree roots, a root itself or
        one without the job entry fails with 126 without running; a checkout
        that cannot be copied into the runner's own directory or an entry
        that cannot start fails with 127; neither leaves a stack, so both
        fail whatever their hold. When the copy of the job before cannot be
        removed, the job fails with 127 and the runner is marked failed with
        the path to remove. None when the record cannot be ended any more,
        named in the job's log.
    """
    with jobs.open_log(root, record.id) as handle:
        try:
            try:
                code, ran = _deploy(record, runner, run, handle)
            except StaleCopyError as exc:
                reason = stale_copy(runner, exc)
                _note(handle, f"job {record.id} did not start: {reason}")
                jobs.mark_failed(root, runner.name, reason)
                return jobs.end(root, record.id, UNSTARTABLE, clock())
            if not ran:
                return jobs.end(root, record.id, code, clock())
            return _close(root, record, runner, code, run, clock, teardown, handle)
        except jobs.JobError as exc:
            _note(handle, f"job {record.id} could not be ended: {exc}")
            return None


def recover(
    root: Path,
    runner: Runner,
    run: Run,
    clock: Callable[[], float],
    teardown: Teardown,
) -> list[jobs.Job]:
    """Args:
        root: the queue directory.
        runner: this runner, starting.
        run: runs a command like :func:`subprocess.run`.
        clock: returns the current time.
        teardown: the command that removes a job stack, by its compose project name.

    Returns:
        Every job still running on this runner, whose deploy died with the
        runner's last start: ended with 137 and never run again, held when it
        was submitted with hold or its stack outlives the removal, else
        failed once that stack is gone.
    """
    ended: list[jobs.Job] = []
    for record in jobs.jobs(root):
        if record.state != jobs.RUNNING or record.runner != runner.name:
            continue
        with jobs.open_log(root, record.id) as handle:
            _note(
                handle,
                f"job {record.id} abandoned: {runner.name} stopped while it ran; "
                "it does not run again",
            )
            ended.append(
                _close(root, record, runner, ABANDONED, run, clock, teardown, handle)
            )
    return ended


def step(
    root: Path,
    runner: Runner,
    run: Run,
    clock: Callable[[], float],
    teardown: Teardown,
) -> jobs.Job | None:
    """Args:
        root: the queue directory.
        runner: this runner.
        run: runs a command like :func:`subprocess.run`.
        clock: returns the current time.
        teardown: the command that removes a job stack, by its compose project name.

    Returns:
        The job this runner claimed and finished, None when it is busy, held,
        marked failed while the copy of the job before still cannot be
        removed, or nothing waits. A marked runner whose copy is gone again
        is unmarked and claims.
    """
    if jobs.failure(root, runner.name):
        try:
            clear_copy(runner, run)
        except StaleCopyError as exc:
            jobs.mark_failed(root, runner.name, stale_copy(runner, exc))
            return None
        jobs.mark_failed(root, runner.name, "")
    record = jobs.claim(root, runner.name, runner.name, clock())
    if record is None:
        return None
    return run_job(root, record, runner, run, clock, teardown)


def serve(
    root: Path,
    runner: Runner,
    run: Run,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    poll: float,
    teardown: Teardown,
) -> None:
    """
    Args:
        root: the queue directory.
        runner: this runner.
        run: runs a command like :func:`subprocess.run`.
        clock: returns the current time.
        sleep: waits the given seconds.
        poll: seconds between two looks at the queue while nothing is claimed;
            a runner marked failed waits :data:`FAILED_POLL` seconds instead
            before it tries the removal as root again.
        teardown: the command that removes a job stack, by its compose project name.

    Returns:
        Never; its process serves the queue as ``runner``, holding the
        runner's registration locked, until it dies.
    """
    with jobs.serving(root, runner.name):
        recover(root, runner, run, clock, teardown)
        while True:
            if step(root, runner, run, clock, teardown) is None:
                sleep(FAILED_POLL if jobs.failure(root, runner.name) else poll)
