from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from cli.administration.deploy.development.env import (
    INFRA_CONSUMER,
    POOL_CONSUMER,
    compose_file_args,
)
from cli.administration.deploy.development.profile import Profile
from cli.administration.deploy.pool import teardown
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.env.parser import custom_env_value
from utils.infra_inventory import POOL_KEY
from utils.runner import jobs, loop
from utils.runner.jobs import BUSY, DONE, FAILED, HELD, IDLE, RUNNING

NOW = 1_800_000_000.0
RUNNER = "runner-1"
TARGET = "compose-deploy"
ARGS = ("apps=web-app-dashboard", "mode=reinstall")
RUNNER_OWN_KEYS = (
    "PYTHONPATH",
    "RUNNER_SRC_DIR",
    "INFINITO_RUNNER_QUEUE_DIR",
    "INFINITO_RUNNER_WORKTREE_ROOTS",
    "INFINITO_RUNNER_INSTALL_DIR",
    "INFINITO_RUNNER_CHECKOUT",
    "INFINITO_RUNNER_IMAGE",
)
IMAGE = "infinito/arch:0123abcd"
RUNNER_ENV = {
    "INFINITO_SUBNET": "172.30.1.0/24",
    "COMPOSE_PROJECT_NAME": RUNNER,
    "PYTHONPATH": "/home/operator/Repositories/core",
    "RUNNER_SRC_DIR": "/home/operator/Repositories/core",
    "INFINITO_RUNNER_QUEUE_DIR": "/var/cache/infinito/core/cache/jobs",
    "INFINITO_RUNNER_WORKTREE_ROOTS": "/home/operator/Repositories/core",
    "INFINITO_RUNNER_INSTALL_DIR": "/opt/github-runner/1",
    "INFINITO_RUNNER_CHECKOUT": "/opt/github-runner/1/checkout",
    "INFINITO_RUNNER_IMAGE": IMAGE,
}
DEPLOY_LINE = "TASK [web-app-dashboard] ok\n"
RACERS = 8
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
CHILD = """
import contextlib, subprocess, sys, time
from pathlib import Path
from utils.runner import jobs, loop

root, name, barrier, mode = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4]
written = jobs._write

def slow_write(*args):
    time.sleep(0.3)
    return written(*args)

def run(argv, **kwargs):
    if argv[1:2] == ["make"]:
        print("deployed", flush=True)
    return subprocess.CompletedProcess(argv, 0)

jobs._write = slow_write
if mode == "unlocked":
    jobs._locked = lambda _root: contextlib.nullcontext()
(barrier.parent / f"ready-{name}").touch()
while not barrier.exists():
    time.sleep(0.005)
install = root.parent / "install" / name
install.mkdir(parents=True)
runner = loop.Runner(
    name=name,
    roots=(root.parent / "worktrees",),
    install=install,
    checkout=install / "checkout",
    image="toolchain",
    env={},
)
loop.step(root, runner, run, lambda: 0.0, lambda stack: ["true", stack])
"""


def git(cwd: Path, *argv: str) -> str:
    """Args:
        cwd: the directory git runs in.
        argv: the git arguments.

    Returns:
        What git printed, stripped.
    """
    return subprocess.run(
        ["git", *argv],
        cwd=cwd,
        env=GIT_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def make_checkout(checkout: Path) -> Path:
    """Args:
        checkout: where the git repository with one commit goes.

    Returns:
        The checkout, holding the job entry, a tracked file and link, an
        ignored ``build/`` and ``secret``, an untracked ``notes.txt`` and
        ``.env``.
    """
    (checkout / loop.ENTRY).parent.mkdir(parents=True)
    (checkout / loop.ENTRY).write_text("#!/bin/sh\n", encoding="utf-8")
    (checkout / "roles").mkdir()
    (checkout / "roles" / "main.yml").write_text("---\n", encoding="utf-8")
    (checkout / "link").symlink_to("roles")
    (checkout / ".gitignore").write_text(
        f"build/\nsecret\n{loop.CUSTOM_ENV}\n", encoding="utf-8"
    )
    git(checkout, "init", "-q")
    git(checkout, "add", "--all")
    git(checkout, "commit", "-qm", "init")
    (checkout / "notes.txt").write_text("untracked\n", encoding="utf-8")
    (checkout / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    (checkout / "build" / "big").mkdir(parents=True)
    (checkout / "build" / "big" / "blob").write_bytes(b"\0" * 1024)
    (checkout / "secret").write_text("private\n", encoding="utf-8")
    (checkout / "secret").chmod(0o000)
    return checkout


class _StopError(Exception):
    pass


class _Wiping:
    def __init__(self, runner: loop.Runner, run, code: int = 0) -> None:
        """
        Args:
            runner: the runner whose copy the wipe container removes.
            run: what every other command goes to.
            code: the exit status of the wipe; on 0 the copy goes as
                ``rm -rf`` removes it.
        """
        self.runner = runner
        self.run = run
        self.code = code
        self.wipes = 0

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess:
        if list(argv) != loop.wipe_command(self.runner):
            return self.run(argv, **kwargs)
        self.wipes += 1
        path = self.runner.checkout
        if self.code == 0 and path.is_symlink():
            path.unlink()
        elif self.code == 0 and path.exists():
            shutil.rmtree(path)
        return subprocess.CompletedProcess(list(argv), self.code, "", "rm: denied")


class _Run:
    """
    Args:
        codes: the exit status per call, in call order.
        unstartable: raise this instead of running the job entry.
    """

    def __init__(self, codes: list[int], unstartable: OSError | None) -> None:
        self.codes = list(codes)
        self.unstartable = unstartable
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append({"argv": list(argv), **kwargs})
        if self.unstartable is not None and argv[0].endswith(str(loop.ENTRY)):
            raise self.unstartable
        kwargs["stdout"].write(DEPLOY_LINE)
        return subprocess.CompletedProcess(argv, self.codes.pop(0))


class _Loop(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(self._tmp.name))
        self.worktrees = base / "worktrees"
        self.checkout = make_checkout(self.worktrees / "feature-x")
        self.root = base / "jobs"
        self.install = base / "install" / "1"
        self.install.mkdir(parents=True)
        self.copy = self.install / "checkout"
        self.runner = loop.Runner(
            name=RUNNER,
            roots=(self.worktrees,),
            install=self.install,
            checkout=self.copy,
            image=IMAGE,
            env=dict(RUNNER_ENV),
        )
        self.wipe_code = 0
        jobs.register(self.root, RUNNER)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _submit(self, hold: bool, checkout: Path | None = None) -> jobs.Job:
        where = self.checkout if checkout is None else checkout
        return jobs.submit(self.root, str(where), TARGET, ARGS, hold, NOW)

    def _step(self, run) -> jobs.Job | None:
        wiping = _Wiping(self.runner, run, self.wipe_code)
        return loop.step(self.root, self.runner, wiping, lambda: NOW, teardown)

    def _log(self, record: jobs.Job) -> str:
        return read_text(str(jobs.log_path(self.root, record.id)))


class TestTheJobRunsThroughTheEntry(_Loop):
    def test_a_claimed_job_runs_its_copys_entry_against_the_runners_stack(
        self,
    ) -> None:
        self._submit(hold=False)
        run = _Run([0, 0], None)
        self._step(run)
        deploy = run.calls[0]
        self.assertEqual(
            deploy["argv"],
            [f"{self.copy}/scripts/tests/deploy/job/entry.sh", "make", TARGET, *ARGS],
        )
        self.assertEqual(deploy["cwd"], str(self.copy))
        self.assertEqual(deploy["env"][loop.STACK_KEY], RUNNER)
        self.assertEqual(deploy["env"]["INFINITO_SUBNET"], "172.30.1.0/24")

    def test_the_job_gets_none_of_the_runners_own_keys(self) -> None:
        self._submit(hold=False)
        run = _Run([0, 0], None)
        self._step(run)
        env = run.calls[0]["env"]
        self.assertEqual([key for key in RUNNER_OWN_KEYS if key not in RUNNER_ENV], [])
        self.assertEqual([key for key in RUNNER_OWN_KEYS if key in env], [])
        self.assertEqual(
            [key for key in RUNNER_OWN_KEYS if key in loop.job_env(self.runner)], []
        )
        self.assertTrue(all(key in RUNNER_ENV for key in loop.RUNNER_ONLY))

    def test_the_job_writes_no_bytecode_and_declares_the_pool_runner(self) -> None:
        self._submit(hold=False)
        run = _Run([0, 0], None)
        self._step(run)
        env = run.calls[0]["env"]
        self.assertEqual(
            [env["PYTHONDONTWRITEBYTECODE"], env[loop.POOL_RUNNER_KEY]], ["1", "true"]
        )
        self.assertNotIn("INFINITO_CACHE_STACK", env)

    def test_a_job_whose_record_cannot_be_ended_returns_none_and_says_so(
        self,
    ) -> None:
        record = self._submit(hold=True)
        with mock.patch.object(jobs, "finish", side_effect=jobs.JobError("gone")):
            self.assertIsNone(self._step(_Run([0], None)))
        self.assertIn(f"job {record.id} could not be ended: gone", self._log(record))

    def test_the_exit_status_and_the_output_reach_the_job(self) -> None:
        for code, state in ((0, DONE), (3, FAILED)):
            record = self._submit(hold=False)
            ended = self._step(_Run([code, 0], None))
            with self.subTest(code=code):
                self.assertEqual(
                    [ended.id, ended.state, ended.exit_code], [record.id, state, code]
                )
                self.assertIn(DEPLOY_LINE, self._log(record))

    def test_an_entry_that_cannot_start_fails_the_job_instead_of_hanging(
        self,
    ) -> None:
        record = self._submit(hold=False)
        ended = self._step(_Run([0], FileNotFoundError("entry.sh")))
        self.assertEqual([ended.state, ended.exit_code], [FAILED, loop.UNSTARTABLE])
        self.assertIn(f"job {record.id} did not start", self._log(record))
        self.assertEqual(jobs.runners(self.root), {RUNNER: IDLE})

    def test_an_unstarted_job_fails_without_a_stack_even_with_hold(self) -> None:
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        for checkout, unstartable, code in (
            (outside, None, loop.REFUSED),
            (self.checkout, FileNotFoundError("entry.sh"), loop.UNSTARTABLE),
        ):
            self._submit(hold=True, checkout=checkout)
            run = _Run([0], unstartable)
            ended = self._step(run)
            with self.subTest(code=code):
                self.assertEqual([ended.state, ended.exit_code], [FAILED, code])
                self.assertEqual(jobs.runners(self.root), {RUNNER: IDLE})
                self.assertEqual(
                    [
                        call["argv"]
                        for call in run.calls
                        if call["argv"][1:2] != ["make"]
                    ],
                    [],
                )

    def test_nothing_queued_runs_nothing(self) -> None:
        run = _Run([], None)
        self.assertIsNone(self._step(run))
        self.assertEqual(run.calls, [])


class TestTheCheckoutStaysInsideTheRoots(_Loop):
    def test_a_checkout_outside_every_root_is_refused_without_running(self) -> None:
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        link = self.worktrees / "escape"
        link.symlink_to(outside)
        climbed = self.worktrees / os.path.relpath(outside, self.worktrees)
        for checkout in (outside, link, climbed):
            record = self._submit(hold=False, checkout=checkout)
            run = _Run([0], None)
            ended = self._step(run)
            with self.subTest(checkout=str(checkout)):
                self.assertEqual([ended.state, ended.exit_code], [FAILED, loop.REFUSED])
                self.assertEqual(run.calls, [])
                self.assertIn("resolves outside the worktree roots", self._log(record))

    def test_an_empty_or_relative_checkout_is_refused_even_from_inside_a_root(
        self,
    ) -> None:
        for checkout in ("", ".", self.checkout.name, "feature-x/../feature-x"):
            jobs.submit(self.root, checkout, TARGET, ARGS, False, NOW)
            run = _Run([0, 0], None)
            with contextlib.chdir(self.worktrees):
                ended = self._step(run)
                resolved = loop.confined(checkout, self.runner.roots)
            with self.subTest(checkout=checkout):
                self.assertEqual([ended.state, ended.exit_code], [FAILED, loop.REFUSED])
                self.assertEqual(run.calls, [])
                self.assertIsNone(resolved)

    def test_a_checkout_inside_a_root_runs(self) -> None:
        self.assertEqual(
            loop.confined(str(self.checkout), self.runner.roots),
            Path(os.path.realpath(self.checkout)),
        )
        self.assertIsNone(loop.confined(self._tmp.name, self.runner.roots))
        self.assertIsNone(loop.confined(f"{self.checkout}\0", self.runner.roots))

    def test_a_root_itself_or_a_checkout_without_the_job_entry_is_refused(
        self,
    ) -> None:
        (self.worktrees / loop.ENTRY).parent.mkdir(parents=True)
        (self.worktrees / loop.ENTRY).write_text("#!/bin/sh\n", encoding="utf-8")
        bare = self.worktrees / "bare"
        bare.mkdir()
        for checkout in (self.worktrees, bare):
            record = self._submit(hold=False, checkout=checkout)
            run = _Run([0], None)
            ended = self._step(run)
            with self.subTest(checkout=str(checkout)):
                self.assertEqual([ended.state, ended.exit_code], [FAILED, loop.REFUSED])
                self.assertEqual(run.calls, [])
                self.assertIn(f"holds no {loop.ENTRY}", self._log(record))


class TestTheJobRunsFromACopy(_Loop):
    def _deployed(self, checkout: Path) -> dict[str, object]:
        self._submit(hold=False, checkout=checkout)
        seen: dict[str, object] = {}

        def deploy(argv, **kwargs) -> subprocess.CompletedProcess:
            if argv[1:2] == ["make"]:
                seen.update(
                    cwd=kwargs["cwd"],
                    entries=sorted(entry.name for entry in self.copy.iterdir()),
                    link=str((self.copy / "link").readlink()),
                    head=git(self.copy, "rev-parse", "HEAD"),
                    top=git(self.copy, "rev-parse", "--show-toplevel"),
                )
            return subprocess.CompletedProcess(argv, 0)

        self._step(deploy)
        return seen

    def test_the_copy_holds_what_git_sees_and_a_resolvable_git_file(self) -> None:
        linked = self.worktrees / "linked"
        git(self.checkout, "worktree", "add", "-q", str(linked))
        tracked = [".git", ".gitignore", loop.CUSTOM_ENV, "link", "roles", "scripts"]
        for checkout, entries in (
            (self.checkout, sorted([*tracked, "notes.txt"])),
            (linked, tracked),
        ):
            seen = self._deployed(checkout)
            with self.subTest(checkout=checkout.name):
                self.assertEqual(
                    seen,
                    {
                        "cwd": str(self.copy),
                        "entries": entries,
                        "link": "roles",
                        "head": git(checkout, "rev-parse", "HEAD"),
                        "top": str(self.copy),
                    },
                )
                self.assertTrue((self.copy / loop.GIT).is_file())
                self.assertTrue((checkout / loop.GIT).exists())

    def test_ignored_unreadable_and_big_files_and_env_are_never_copied(
        self,
    ) -> None:
        seen = self._deployed(self.checkout)
        self.assertNotIn("secret", seen["entries"])
        self.assertNotIn("build", seen["entries"])
        self.assertNotIn(".env", seen["entries"])
        self.assertIn("notes.txt", seen["entries"])
        self.assertTrue((self.copy / "roles" / "main.yml").is_file())

    def test_each_job_replaces_the_copy_the_job_before_left(self) -> None:
        stale = self.copy / "stale" / "file"
        stale.parent.mkdir(parents=True)
        stale.write_text("left over\n", encoding="utf-8")
        self._submit(hold=False)
        self._step(_Run([0, 0], None))
        self.assertFalse(stale.parent.exists())

    def test_a_link_the_wipe_left_at_the_copy_is_removed_never_followed(
        self,
    ) -> None:
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "keep").write_text("kept\n", encoding="utf-8")
        self.copy.symlink_to(outside)
        loop.clear_copy(
            self.runner,
            lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 0, "", ""),
        )
        self.assertEqual(sorted(path.name for path in outside.iterdir()), ["keep"])
        self.assertTrue(self.copy.is_dir())
        self.assertFalse(self.copy.is_symlink())

    def test_the_operators_custom_env_comes_along_with_the_pool_settings_pinned(
        self,
    ) -> None:
        (self.checkout / loop.CUSTOM_ENV).write_text(
            "INFINITO_DISTRO=debian\nINFINITO_CACHE_STACK=true\n"
            "export INFINITO_DEPLOY_VIA_POOL=true\nINFINITO_POOL_RUNNER=false\n",
            encoding="utf-8",
        )
        self._deployed(self.checkout)
        kept = ("INFINITO_DISTRO", "INFINITO_CACHE_STACK", *loop.POOL_SETTINGS)
        self.assertEqual(
            {key: custom_env_value(self.copy, key) for key in kept},
            {
                "INFINITO_DISTRO": "debian",
                "INFINITO_CACHE_STACK": "true",
                **loop.POOL_SETTINGS,
            },
        )
        self.assertEqual(loop.POOL_SETTINGS[loop.POOL_RUNNER_KEY], "true")

    def test_the_copied_custom_env_is_readable_by_its_owner_alone(self) -> None:
        source = self.checkout / loop.CUSTOM_ENV
        source.write_text("INFINITO_DISTRO=debian\n", encoding="utf-8")
        source.chmod(0o644)
        (self.checkout / ".gitignore").chmod(0o644)
        self._deployed(self.checkout)
        self.assertEqual(
            [
                (self.copy / loop.CUSTOM_ENV).stat().st_mode & 0o777,
                (self.copy / ".gitignore").stat().st_mode & 0o777,
            ],
            [0o600, 0o644],
        )

    def test_a_listed_path_through_a_link_out_of_the_copy_creates_nothing_outside(
        self,
    ) -> None:
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (self.checkout / "escape" / "deep").mkdir(parents=True)
        (self.checkout / "escape" / "deep" / "file").write_text("x\n", encoding="utf-8")
        loop.copy_checkout(self.checkout, self.copy, self.install)
        self.assertTrue((self.copy / "escape" / "deep" / "file").is_file())
        shutil.rmtree(self.copy / "escape")
        (self.copy / "escape").symlink_to(outside)
        with self.assertRaises(OSError):
            loop.copy_checkout(self.checkout, self.copy, self.install)
        self.assertEqual(list(outside.iterdir()), [])

    def test_without_a_custom_env_the_copy_carries_the_pool_settings_alone(
        self,
    ) -> None:
        self._deployed(self.checkout)
        self.assertEqual(
            read_text(str(self.copy / loop.CUSTOM_ENV)).splitlines(),
            [f"{key}={value}" for key, value in loop.POOL_SETTINGS.items()],
        )

    def test_a_sync_mirrors_renames_and_removals_but_keeps_what_the_job_wrote(
        self,
    ) -> None:
        loop.copy_checkout(self.checkout, self.copy, self.install)
        written = self.copy / "build" / "lib.egg-info" / "PKG-INFO"
        written.parent.mkdir(parents=True)
        written.write_text("job\n", encoding="utf-8")
        (self.checkout / "notes.txt").rename(self.checkout / "renamed.txt")
        git(self.checkout, "rm", "-q", "roles/main.yml")
        loop.copy_checkout(self.checkout, self.copy, self.install)
        self.assertEqual(
            [
                (self.copy / "notes.txt").exists(),
                (self.copy / "roles" / "main.yml").exists(),
                (self.copy / "renamed.txt").is_file(),
                written.is_file(),
            ],
            [False, False, True, True],
        )

    def test_without_the_list_of_the_copy_before_nothing_is_removed(self) -> None:
        loop.copy_checkout(self.checkout, self.copy, self.install)
        (self.install / loop.MANIFEST).unlink()
        (self.checkout / "notes.txt").unlink()
        loop.copy_checkout(self.checkout, self.copy, self.install)
        self.assertTrue((self.copy / "notes.txt").is_file())

    def test_an_unmounted_git_directory_fails_unstarted_even_with_hold(
        self,
    ) -> None:
        linked = self.worktrees / "moved"
        (linked / loop.ENTRY).parent.mkdir(parents=True)
        (linked / loop.ENTRY).write_text("#!/bin/sh\n", encoding="utf-8")
        (linked / loop.GIT).write_text("gitdir: /nonexistent/.git\n", encoding="utf-8")
        record = self._submit(hold=True, checkout=linked)
        run = _Run([0], None)
        ended = self._step(run)
        self.assertEqual([ended.state, ended.exit_code], [FAILED, loop.UNSTARTABLE])
        self.assertEqual(run.calls, [])
        self.assertIn("does not mount", self._log(record))
        self.assertEqual(jobs.runners(self.root), {RUNNER: IDLE})


class TestTheCopyGoesAsRoot(_Loop):
    def test_the_wipe_runs_as_root_on_the_install_directory_alone(self) -> None:
        command = loop.wipe_command(self.runner)
        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertEqual(
            [command[command.index(flag) + 1] for flag in ("--user", "--network")],
            ["0:0", "none"],
        )
        volumes = [command[i + 1] for i, arg in enumerate(command) if arg == "--volume"]
        self.assertEqual(volumes, [f"{self.install}:{loop.WIPE_MOUNT}"])
        self.assertEqual(command[command.index("--entrypoint") + 1], "rm")
        self.assertEqual(
            command[command.index(IMAGE) :],
            [IMAGE, "-rf", "--one-file-system", "--", f"{loop.WIPE_MOUNT}/checkout"],
        )

    def test_root_owned_residue_never_blocks_the_next_job(self) -> None:
        residue = self.copy / "build" / "lib.egg-info"
        residue.mkdir(parents=True)
        self._submit(hold=False)
        run = _Run([0, 0], None)
        wiping = _Wiping(self.runner, run)
        loop.step(self.root, self.runner, wiping, lambda: NOW, teardown)
        self.assertEqual([wiping.wipes, residue.exists()], [1, False])
        self.assertEqual(run.calls[0]["argv"][0], str(self.copy / loop.ENTRY))

    def test_a_failed_wipe_fails_the_runner_once_and_it_resumes_after_one(
        self,
    ) -> None:
        self.wipe_code = 1
        first = self._submit(hold=False)
        run = _Run([0, 0], None)
        ended = self._step(run)
        self.assertEqual([ended.id, ended.exit_code], [first.id, loop.UNSTARTABLE])
        self.assertEqual(jobs.runners(self.root), {RUNNER: FAILED})
        self.assertIn(str(self.copy), jobs.failure(self.root, RUNNER))
        self.assertIn("rm: denied", jobs.failure(self.root, RUNNER))
        waiting = self._submit(hold=False)
        self.assertIsNone(self._step(run))
        self.assertEqual(run.calls, [])
        self.assertEqual(jobs.job(self.root, waiting.id).state, jobs.QUEUED)
        self.wipe_code = 0
        self.assertEqual(self._step(run).id, waiting.id)
        self.assertEqual(jobs.failure(self.root, RUNNER), "")
        self.assertEqual(jobs.runners(self.root), {RUNNER: IDLE})

    def _slept(self, wipe_code: int) -> list[float]:
        slept: list[float] = []

        def sleep(seconds: float) -> None:
            slept.append(seconds)
            if len(slept) == 2:
                raise _StopError

        wiping = _Wiping(self.runner, _Run([], None), wipe_code)
        with self.assertRaises(_StopError):
            loop.serve(self.root, self.runner, wiping, lambda: NOW, sleep, 2, teardown)
        return [*slept, wiping.wipes]

    def test_a_failed_runner_retries_the_wipe_once_per_failed_poll(self) -> None:
        jobs.mark_failed(self.root, RUNNER, "rm as root failed")
        self.assertEqual(self._slept(1), [loop.FAILED_POLL, loop.FAILED_POLL, 2])
        self.assertGreater(loop.FAILED_POLL, 2)

    def test_an_idle_runner_polls_the_queue_at_the_short_poll(self) -> None:
        self.assertEqual(self._slept(1), [2, 2, 0])

    def test_a_failed_runner_whose_wipe_succeeds_polls_short_again(self) -> None:
        jobs.mark_failed(self.root, RUNNER, "rm as root failed")
        self.assertEqual(self._slept(0), [2, 2, 1])


class TestAJobUsesTheInfraCachesButNeverStartsOrJoinsIt(_Loop):
    def _layered(self, env: dict[str, str]) -> tuple[bool, list[str]]:
        with mock.patch.dict(os.environ, env, clear=True):
            return Profile().cache_stack_enabled(), compose_file_args()

    def test_the_job_env_takes_the_caches_without_the_infra_network(self) -> None:
        enabled, files = self._layered(loop.job_env(self.runner))
        self.assertEqual(
            [enabled, POOL_CONSUMER in files, INFRA_CONSUMER in files],
            [True, True, False],
        )
        self.assertEqual(loop.job_env(self.runner)[POOL_KEY], "false")

    def test_without_the_pool_runner_the_same_env_attaches_from_the_host(
        self,
    ) -> None:
        env = {**loop.job_env(self.runner), loop.POOL_RUNNER_KEY: ""}
        enabled, files = self._layered(env)
        self.assertEqual(
            [enabled, POOL_CONSUMER in files, INFRA_CONSUMER in files],
            [True, False, True],
        )


class TestTheStackAfterTheJob(_Loop):
    def test_a_job_without_hold_leaves_no_stack_and_an_idle_runner(self) -> None:
        self._submit(hold=False)
        run = _Run([0, 0], None)
        self._step(run)
        self.assertEqual(len(run.calls), 2)
        self.assertEqual(run.calls[1]["argv"], teardown(RUNNER))
        self.assertEqual(run.calls[1]["cwd"], str(self.root))
        self.assertEqual(jobs.runners(self.root), {RUNNER: IDLE})

    def test_a_held_job_keeps_its_stack_and_its_runner(self) -> None:
        self._submit(hold=True)
        run = _Run([0], None)
        ended = self._step(run)
        self.assertEqual(ended.state, HELD)
        self.assertEqual(len(run.calls), 1)
        self.assertEqual(jobs.runners(self.root), {RUNNER: HELD})

    def test_a_held_runner_claims_nothing_until_the_release(self) -> None:
        self._submit(hold=True)
        held = self._step(_Run([0], None))
        waiting = self._submit(hold=False)
        run = _Run([0, 0], None)
        self.assertIsNone(self._step(run))
        self.assertEqual(run.calls, [])
        self.assertEqual(jobs.job(self.root, waiting.id).state, jobs.QUEUED)
        jobs.release(self.root, held.id)
        self.assertEqual(self._step(run).id, waiting.id)

    def test_a_failed_teardown_keeps_the_runner_held_while_its_stack_exists(
        self,
    ) -> None:
        record = self._submit(hold=False)
        ended = self._step(_Run([0, 1], None))
        self.assertEqual([ended.state, ended.exit_code], [HELD, 0])
        self.assertEqual(jobs.runners(self.root), {RUNNER: HELD})
        log = self._log(record)
        self.assertIn(f"removing stack {RUNNER} failed (rc=1)", log)
        self.assertIn(jobs.RELEASE.format(id=record.id), log)
        waiting = self._submit(hold=False)
        self.assertIsNone(self._step(_Run([], None)))
        jobs.release(self.root, record.id)
        self.assertEqual(jobs.job(self.root, record.id).state, DONE)
        self.assertEqual(self._step(_Run([0, 0], None)).id, waiting.id)

    def test_a_removal_that_cannot_start_keeps_the_runner_held(self) -> None:
        self._submit(hold=False)

        def run(argv, **kwargs) -> subprocess.CompletedProcess:
            if argv == teardown(RUNNER):
                raise FileNotFoundError("docker")
            return subprocess.CompletedProcess(argv, 0)

        self.assertEqual(self._step(run).state, HELD)

    def test_the_removal_targets_the_runners_own_stack_only(self) -> None:
        self._submit(hold=False)
        run = _Run([0, 0], None)
        self._step(run)
        self.assertEqual(run.calls[1]["argv"][-4:-2], [RUNNER, "down"])


class TestRecoveryAfterAStop(_Loop):
    def _running(self, hold: bool, runner: str) -> jobs.Job:
        jobs.register(self.root, runner)
        record = self._submit(hold=hold)
        jobs.claim(self.root, runner, runner, NOW)
        return record

    def test_a_job_the_runner_died_under_fails_once_its_stack_is_gone(self) -> None:
        record = self._running(hold=False, runner=RUNNER)
        run = _Run([0], None)
        ended = loop.recover(self.root, self.runner, run, lambda: NOW, teardown)
        self.assertEqual(
            [(job.id, job.state, job.exit_code) for job in ended],
            [(record.id, FAILED, loop.ABANDONED)],
        )
        self.assertEqual([call["argv"] for call in run.calls], [teardown(RUNNER)])
        self.assertIn(f"job {record.id} abandoned", self._log(record))
        self.assertEqual(jobs.runners(self.root), {RUNNER: IDLE})

    def test_a_held_or_unremovable_job_stays_held(self) -> None:
        for hold, codes in ((True, []), (False, [1])):
            record = self._running(hold=hold, runner=RUNNER)
            ended = loop.recover(
                self.root, self.runner, _Run(codes, None), lambda: NOW, teardown
            )
            with self.subTest(hold=hold):
                self.assertEqual([job.state for job in ended], [HELD])
                self.assertEqual(jobs.runners(self.root)[RUNNER], HELD)
            jobs.release(self.root, record.id)

    def test_another_runners_job_and_a_queued_job_are_left_alone(self) -> None:
        other = self._running(hold=False, runner="runner-2")
        queued = self._submit(hold=False)
        run = _Run([], None)
        self.assertEqual(
            loop.recover(self.root, self.runner, run, lambda: NOW, teardown), []
        )
        self.assertEqual(run.calls, [])
        self.assertEqual(jobs.job(self.root, other.id).state, RUNNING)
        self.assertEqual(jobs.job(self.root, queued.id).state, jobs.QUEUED)

    def test_serve_ends_the_abandoned_job_before_it_claims_and_never_reruns_it(
        self,
    ) -> None:
        abandoned = self._running(hold=False, runner=RUNNER)
        waiting = self._submit(hold=False)
        run = _Run([0, 0, 0], None)

        def sleep(_seconds: float) -> None:
            raise _StopError

        wiping = _Wiping(self.runner, run)
        with self.assertRaises(_StopError):
            loop.serve(self.root, self.runner, wiping, lambda: NOW, sleep, 1, teardown)
        deploys = [call for call in run.calls if call["argv"][1:2] == ["make"]]
        self.assertEqual(len(deploys), 1)
        self.assertEqual(jobs.job(self.root, abandoned.id).state, FAILED)
        self.assertEqual(jobs.job(self.root, waiting.id).state, DONE)


class TestThePool(_Loop):
    def _race(self, mode: str) -> int:
        self._submit(hold=False)
        barrier = Path(self._tmp.name) / "barrier" / "go"
        barrier.parent.mkdir()
        env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
        children = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    CHILD,
                    str(self.root),
                    f"runner-{n}",
                    str(barrier),
                    mode,
                ],
                cwd=PROJECT_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for n in range(1, RACERS + 1)
        ]
        deadline = time.monotonic() + 60
        while len(list(barrier.parent.glob("ready-*"))) < RACERS:
            self.assertLess(time.monotonic(), deadline, "racers did not start")
            time.sleep(0.01)
        barrier.touch()
        outputs = [child.communicate(timeout=60)[0] for child in children]
        return sum(output.count("deployed") for output in outputs)

    def test_one_job_runs_on_exactly_one_of_eight_runner_processes(self) -> None:
        self.assertEqual(self._race("locked"), 1)

    def test_without_the_queue_lock_the_same_race_runs_the_job_twice(self) -> None:
        self.assertGreater(self._race("unlocked"), 1)

    def test_serve_registers_and_takes_a_job_that_arrives_while_it_polls(
        self,
    ) -> None:
        install = self.install.parent / "2"
        install.mkdir()
        other = loop.Runner(
            name="runner-2",
            roots=(self.worktrees,),
            install=install,
            checkout=install / "checkout",
            image=IMAGE,
            env=RUNNER_ENV,
        )
        run = _Run([0, 0], None)
        sleeps: list[int] = []

        def sleep(_seconds: float) -> None:
            sleeps.append(1)
            self.assertEqual(jobs.runners(self.root)[other.name], IDLE)
            if len(sleeps) == 1:
                self._submit(hold=False)
                return
            raise _StopError

        with self.assertRaises(_StopError):
            loop.serve(
                self.root, other, _Wiping(other, run), lambda: NOW, sleep, 1, teardown
            )
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(run.calls[0]["env"][loop.STACK_KEY], other.name)
        self.assertEqual([record.state for record in jobs.jobs(self.root)], [DONE])

    def test_serve_keeps_its_runner_serving_until_it_stops(self) -> None:
        seen: list[bool] = []

        def sleep(_seconds: float) -> None:
            seen.append(jobs.is_serving(self.root, RUNNER))
            raise _StopError

        with self.assertRaises(_StopError):
            loop.serve(
                self.root, self.runner, _Run([], None), lambda: NOW, sleep, 1, teardown
            )
        self.assertEqual([seen, jobs.is_serving(self.root, RUNNER)], [[True], False])

    def test_a_running_job_shows_its_runner_busy_to_the_pool(self) -> None:
        self._submit(hold=False)

        def deploy(argv, **kwargs) -> subprocess.CompletedProcess:
            self.assertEqual(jobs.runners(self.root), {RUNNER: BUSY})
            self.assertEqual(jobs.jobs(self.root)[0].state, RUNNING)
            return subprocess.CompletedProcess(argv, 0)

        self._step(deploy)
        self.assertEqual(jobs.runners(self.root), {RUNNER: IDLE})


if __name__ == "__main__":
    unittest.main()
