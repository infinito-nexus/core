from __future__ import annotations

import dataclasses
import subprocess
from typing import TYPE_CHECKING

from utils.runner import jobs
from utils.runner.checkout import ENTRY, POOL_SETTINGS, _own, confined, copy_checkout

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path
    from typing import TextIO

    Run = Callable[..., subprocess.CompletedProcess]
    Teardown = Callable[[str], Sequence[str]]

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
