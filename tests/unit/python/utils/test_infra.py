from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from utils import infra, infra_inventory
from utils.cache.evict import Usage
from utils.cache.yaml import load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable


class TestRunnerIp(unittest.TestCase):
    def test_the_runner_takes_host_two(self) -> None:
        self.assertEqual(infra.runner_ip("10.47.0.0/24"), "10.47.0.2")

    def test_a_wider_subnet_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            infra.runner_ip("10.47.0.0/16")

    def test_a_host_address_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            infra.runner_ip("10.47.0.5/24")


class TestWorktreeRoots(unittest.TestCase):
    def test_empty_mounts_the_primary_and_the_worktree_home(self) -> None:
        roots = infra.worktree_roots("", Path("/srv/core"), Path("/home/me"))
        self.assertEqual(
            roots, [Path("/srv/core"), Path("/home/me/.local/share/worktrees")]
        )

    def test_only_the_declared_roots_are_visible(self) -> None:
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            roots = infra.worktree_roots(f"{one}:{two}", Path("/srv/core"), Path("/h"))
        self.assertEqual(roots, [Path(one), Path(two)])

    def test_a_relative_root_is_refused_naming_it(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            infra.worktree_roots("relative/root", Path("/srv/core"), Path("/h"))
        self.assertIn("relative/root", str(ctx.exception.code))


class TestUp(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.lock = Path(self.tmp.name) / "infra.lock"
        self.base = Path(self.tmp.name) / "spare" / "cache"
        self.calls: list[list[str]] = []
        self.pins: list[str] = []
        self.pinned = True
        self.evict_fails = False

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _up(
        self,
        refusal: list[str],
        running: bool,
        recreate: bool,
        foreign: tuple[str, ...] = (),
        run: Callable[[list[str]], None] | None = None,
    ) -> int:
        return infra.up(
            ["compose"],
            refusal=lambda: refusal,
            foreign=lambda: list(foreign),
            running=lambda: running,
            run=run or self.calls.append,
            lock=self.lock,
            base=self.base,
            recreate=recreate,
            takeover=[],
            bridge=None,
            installs=self._installs,
            prepare=self._prepare_pin,
            apply=self._apply_pin,
            evict=self._evict,
        )

    def _installs(self) -> list[list[str]]:
        self.calls.append(["build installs"])
        return [["timer"]]

    def _prepare_pin(self) -> None:
        self.pins.append("prepare")
        if not self.pinned:
            raise SystemExit("no cache pin")

    def _apply_pin(self) -> None:
        self.pins.append("apply")

    def _evict(self) -> None:
        self.pins.append("evict")
        if self.evict_fails:
            raise RuntimeError("evict failed")

    def _sequence(
        self,
        running: bool,
        recreate: bool,
        failing: str = "",
        fresh: bool = False,
    ) -> list[str]:
        """Args:
            running: whether the runner already runs.
            recreate: whether the call is infra-update.
            failing: the command that raises, none when empty.
            fresh: Nexus still has its install password and no tasks, so the
                eviction fails with 401 until the apply's bootstrap ran.

        Returns:
            The pin steps and the runner commands in the order the call ran them,
            then ``raised <reason>`` when the call propagated a failure.
        """
        steps: list[str] = []

        def run(argv: list[str]) -> None:
            steps.append(" ".join(argv))
            if argv == [failing]:
                raise RuntimeError(failing)
            if fresh and argv == ["evict"] and "apply pin" not in steps:
                raise RuntimeError("evict got 401")

        try:
            infra.up(
                ["compose"],
                refusal=list,
                foreign=list,
                running=lambda: running,
                run=run,
                lock=self.lock,
                base=self.base,
                recreate=recreate,
                takeover=[],
                bridge=None,
                installs=lambda: [["deploy-package-cache"], ["timer"]],
                prepare=lambda: steps.append("prepare pin"),
                apply=lambda: steps.append("apply pin"),
                evict=lambda: run(["evict"]),
            )
        except RuntimeError as exc:
            steps.append(f"raised {exc}")
        return steps

    def _takeover(
        self,
        refusal: list[str],
        failing: str,
        *,
        running: bool,
        foreign: tuple[str, ...] = (),
    ) -> int:
        def run(argv: list[str]) -> None:
            recorded = self.lock.with_name(infra.BRIDGE_NAME).is_file()
            marked = self.lock.with_name(infra.OWNER_NAME).is_file()
            self.calls.append([*argv, f"marked={marked and recorded}"])
            if failing and failing in argv:
                raise RuntimeError(f"{failing} failed")

        return infra.up(
            ["compose"],
            refusal=lambda: refusal,
            foreign=lambda: list(foreign),
            running=lambda: running,
            run=run,
            lock=self.lock,
            base=self.base,
            recreate=False,
            takeover=["legacy-a", "legacy-b"],
            bridge=("legacy-net", "172.30.0.6"),
            installs=lambda: [["deploy-registry-cache"]],
            prepare=self._prepare_pin,
            apply=self._apply_pin,
            evict=self._evict,
        )

    def test_a_start_prepares_the_pin_applies_it_then_evicts(self) -> None:
        self.assertEqual(
            self._sequence(running=False, recreate=False),
            [
                "prepare pin",
                "compose up --detach --wait",
                "deploy-package-cache",
                "timer",
                "apply pin",
                "evict",
            ],
        )

    def test_a_fresh_nexus_is_evicted_only_after_the_apply_rotated_it(self) -> None:
        steps = self._sequence(running=False, recreate=False, fresh=True)
        self.assertEqual(steps[-2:], ["apply pin", "evict"])

    def test_a_failed_eviction_comes_after_the_one_apply_then_raises(self) -> None:
        steps = self._sequence(running=False, recreate=False, failing="evict")
        self.assertEqual(steps[-3:], ["apply pin", "evict", "raised evict"])
        self.assertEqual(steps.count("apply pin"), 1)

    def test_a_failed_deploy_applies_and_raises_without_evicting(self) -> None:
        self.assertEqual(
            self._sequence(
                running=False, recreate=False, failing="deploy-package-cache"
            ),
            [
                "prepare pin",
                "compose up --detach --wait",
                "deploy-package-cache",
                "apply pin",
                "raised deploy-package-cache",
            ],
        )

    def test_an_interrupt_during_the_installs_applies_nothing(self) -> None:
        def interrupt(argv: list[str]) -> None:
            if argv == ["timer"]:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self._up([], False, False, run=interrupt)
        self.assertEqual(self.pins, ["prepare"])

    def test_a_failed_takeover_rolls_back_and_applies_nothing(self) -> None:
        self._rolled_back("deploy-registry-cache")
        self.assertEqual(self.pins, ["prepare"])

    def test_a_failed_eviction_keeps_the_finished_takeover(self) -> None:
        self.evict_fails = True
        with self.assertRaisesRegex(RuntimeError, "evict failed"):
            self._takeover([], "", running=False)
        self.assertNotIn(["compose", "stop"], [call[:-1] for call in self.calls])
        self.assertTrue(self.lock.with_name(infra.OWNER_NAME).is_file())
        self.assertEqual(self.pins, ["prepare", "apply", "evict"])

    def test_an_update_prepares_applies_and_evicts_on_a_running_runner(
        self,
    ) -> None:
        steps = self._sequence(running=True, recreate=True)
        self.assertEqual(
            (steps[0], steps[-2:]), ("prepare pin", ["apply pin", "evict"])
        )

    def test_a_call_that_finds_the_runner_running_only_applies_the_pin(
        self,
    ) -> None:
        with patch("builtins.print"):
            self.assertEqual(
                self._sequence(running=True, recreate=False), ["apply pin"]
            )

    def test_without_a_pin_the_runner_does_not_start(self) -> None:
        self.pinned = False
        with self.assertRaisesRegex(SystemExit, "no cache pin"):
            self._up([], False, False)
        self.assertEqual((self.calls, self.pins), ([], ["prepare"]))

    def test_without_a_pin_a_takeover_restarts_the_legacy_stack(self) -> None:
        self.pinned = False
        with patch("sys.stderr"), self.assertRaisesRegex(SystemExit, "no cache pin"):
            self._takeover([], "", running=False)
        self.assertEqual(
            [call[:-1] for call in self.calls],
            [
                ["docker", "stop", "-t", "120", "legacy-a", "legacy-b"],
                ["compose", "stop"],
                ["docker", "start", "legacy-a", "legacy-b"],
            ],
        )
        self.assertFalse(self.lock.with_name(infra.OWNER_NAME).exists())

    def test_a_refusal_neither_prepares_nor_applies_the_pin(self) -> None:
        with patch("sys.stderr"):
            self._up(["below INFINITO_CACHE_DISK_FLOOR"], False, False)
        self.assertEqual(self.pins, [])

    def test_the_takeover_stops_the_legacy_stack_after_the_mark_before_the_start(
        self,
    ) -> None:
        self._takeover([], "", running=False)
        self.assertEqual(
            self.calls,
            [
                ["docker", "stop", "-t", "120", "legacy-a", "legacy-b", "marked=True"],
                ["compose", "up", "--detach", "--wait", "marked=True"],
                ["deploy-registry-cache", "marked=True"],
            ],
        )
        self.assertEqual(
            infra.read_bridge(self.lock.with_name(infra.BRIDGE_NAME)),
            ("legacy-net", "172.30.0.6"),
        )

    def test_a_takeover_recreates_a_runner_that_already_runs(self) -> None:
        self._takeover([], "", running=True)
        self.assertIn(
            ["compose", "up", "--detach", "--wait", "marked=True"], self.calls
        )

    def test_a_refused_takeover_stops_nothing(self) -> None:
        with patch("sys.stderr"):
            self.assertEqual(self._takeover(["below the floor"], "", running=False), 2)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.lock.with_name(infra.BRIDGE_NAME).exists())

    def _rolled_back(self, failing: str) -> list[list[str]]:
        with patch("sys.stderr"), self.assertRaisesRegex(RuntimeError, failing):
            self._takeover([], failing, running=False)
        self.assertFalse(self.lock.with_name(infra.OWNER_NAME).exists())
        self.assertFalse(self.lock.with_name(infra.BRIDGE_NAME).exists())
        return [call[:-1] for call in self.calls]

    def test_a_failed_runner_start_restarts_the_legacy_stack(self) -> None:
        self.assertEqual(
            self._rolled_back("up")[-2:],
            [["compose", "stop"], ["docker", "start", "legacy-a", "legacy-b"]],
        )

    def test_a_failed_cache_deploy_stops_the_runner_and_restarts_the_legacy_stack(
        self,
    ) -> None:
        self.assertEqual(
            self._rolled_back("deploy-registry-cache")[-2:],
            [["compose", "stop"], ["docker", "start", "legacy-a", "legacy-b"]],
        )

    def test_a_failed_rollback_step_still_runs_the_next(self) -> None:
        self.assertEqual(
            self._rolled_back("stop")[-1],
            ["docker", "start", "legacy-a", "legacy-b"],
        )

    def test_a_failure_without_takeover_rolls_nothing_back(self) -> None:
        def fail(_argv: list[str]) -> None:
            raise RuntimeError("compose up failed")

        with self.assertRaises(RuntimeError):
            infra.up(
                ["compose"],
                refusal=list,
                foreign=list,
                running=lambda: False,
                run=fail,
                lock=self.lock,
                base=self.base,
                recreate=False,
                takeover=[],
                bridge=None,
                installs=list,
                prepare=list,
                apply=list,
                evict=list,
            )
        self.assertTrue(self.lock.with_name(infra.OWNER_NAME).is_file())

    def test_a_floor_refusal_starts_nothing(self) -> None:
        with patch("sys.stderr"):
            code = self._up(["below INFINITO_CACHE_DISK_FLOOR"], False, False)
        self.assertEqual((code, self.calls), (2, []))

    def test_the_installs_are_built_only_after_the_runner_started(self) -> None:
        self._up([], False, False)
        self.assertEqual(
            self.calls[:2],
            [["compose", "up", "--detach", "--wait"], ["build installs"]],
        )

    def test_without_refusal_the_runner_starts(self) -> None:
        self.assertEqual(self._up([], False, False), 0)
        self.assertEqual(
            self.calls,
            [["compose", "up", "--detach", "--wait"], ["build installs"], ["timer"]],
        )

    def test_a_running_runner_is_kept(self) -> None:
        with patch("builtins.print"):
            self._up([], True, False)
        self.assertEqual(self.calls, [])

    def test_update_applies_to_a_running_runner(self) -> None:
        self._up([], True, True)
        self.assertEqual(len(self.calls), 3)

    def test_a_start_marks_the_cache_base_as_owned(self) -> None:
        self._up([], False, False)
        self.assertTrue(self.lock.with_name(infra.OWNER_NAME).is_file())

    def test_a_running_runner_keeps_the_mark(self) -> None:
        with patch("builtins.print"):
            self._up([], True, False)
        self.assertTrue(self.lock.with_name(infra.OWNER_NAME).is_file())

    def test_a_failed_start_still_marks_the_cache_base(self) -> None:
        def fail(_argv: list[str]) -> None:
            raise RuntimeError("compose up failed")

        with self.assertRaises(RuntimeError):
            infra.up(
                ["compose"],
                refusal=list,
                foreign=list,
                running=lambda: False,
                run=fail,
                lock=self.lock,
                base=self.base,
                recreate=False,
                takeover=[],
                bridge=None,
                installs=list,
                prepare=list,
                apply=list,
                evict=list,
            )
        self.assertTrue(self.lock.with_name(infra.OWNER_NAME).is_file())

    def test_a_refusal_marks_nothing(self) -> None:
        with patch("sys.stderr"):
            self._up(["the legacy cache stack still runs"], False, False)
        self.assertFalse(self.lock.with_name(infra.OWNER_NAME).exists())
        self.assertEqual(self.calls, [])

    def test_a_runner_on_another_base_is_neither_kept_nor_recreated(self) -> None:
        for recreate in (False, True):
            with self.subTest(recreate=recreate), patch("sys.stderr"):
                code = self._up([], True, recreate, ("binds another base",))
                self.assertEqual((code, self.calls), (2, []))
        self.assertFalse(self.lock.with_name(infra.OWNER_NAME).exists())

    def test_a_runner_on_another_base_stops_no_legacy_stack(self) -> None:
        with patch("sys.stderr"):
            code = self._takeover([], "", running=True, foreign=("another base",))
        self.assertEqual((code, self.calls), (2, []))
        self.assertFalse(self.lock.with_name(infra.BRIDGE_NAME).exists())

    def test_the_base_exists_before_the_host_daemon_could_create_it(self) -> None:
        seen: list[bool] = []
        infra.up(
            ["compose"],
            refusal=list,
            foreign=list,
            running=lambda: False,
            run=lambda _argv: seen.append(self.base.is_dir()),
            lock=self.lock,
            base=self.base,
            recreate=False,
            takeover=[],
            bridge=None,
            installs=list,
            prepare=list,
            apply=list,
            evict=list,
        )
        self.assertEqual(seen, [True])

    def test_a_base_this_user_cannot_create_starts_nothing(self) -> None:
        with (
            patch("sys.stderr"),
            patch.object(infra, "prepare_base", return_value=["refused"]),
        ):
            code = self._up([], False, False)
        self.assertEqual((code, self.calls), (2, []))
        self.assertFalse(self.lock.with_name(infra.OWNER_NAME).exists())

    def test_a_runner_on_another_base_creates_no_base(self) -> None:
        with patch("sys.stderr"):
            self._up([], True, False, ("binds another base",))
        self.assertFalse(self.base.exists())

    def test_the_lock_lands_in_a_directory_the_call_may_create(self) -> None:
        self.lock = Path(self.tmp.name) / "core" / "cache" / "infra.lock"
        self.assertEqual(self._up([], False, False), 0)
        self.assertTrue(self.lock.with_name(infra.OWNER_NAME).is_file())


class TestBaseRefusal(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_a_writable_base_passes(self) -> None:
        self.assertEqual(infra.base_refusal([self.root]), [])

    def test_a_missing_base_below_a_writable_parent_passes(self) -> None:
        self.assertEqual(infra.base_refusal([self.root / "core" / "cache"]), [])

    def test_a_missing_base_the_user_cannot_create_names_the_install_step(
        self,
    ) -> None:
        with patch.object(infra.os, "access", return_value=False):
            [line] = infra.base_refusal([self.root / "cache"])
        self.assertIn(f'sudo install -d -o "$USER" {self.root / "cache"}', line)

    def test_a_foreign_base_names_the_chown_step(self) -> None:
        with patch.object(infra.os, "access", return_value=False):
            [line] = infra.base_refusal([self.root])
        self.assertIn(f'sudo chown "$USER": {self.root}', line)

    def test_the_lock_directory_and_a_moved_base_are_both_checked(self) -> None:
        moved = self.root / "moved"
        moved.mkdir()
        with patch.object(
            infra.os, "access", side_effect=lambda path, _mode: Path(path) != moved
        ):
            [line] = infra.base_refusal([self.root, moved])
        self.assertIn(str(moved), line)

    def test_one_directory_named_twice_is_refused_once(self) -> None:
        with patch.object(infra.os, "access", return_value=False):
            self.assertEqual(len(infra.base_refusal([self.root, self.root])), 1)

    def test_preparing_a_missing_base_creates_it_as_this_user(self) -> None:
        base = self.root / "mnt" / "cache"
        self.assertEqual(infra.prepare_base(base), [])
        self.assertEqual(base.stat().st_uid, self.root.stat().st_uid)

    def test_a_base_this_user_cannot_create_is_refused_and_left_alone(self) -> None:
        base = self.root / "mnt" / "cache"
        with patch.object(infra.os, "access", return_value=False):
            [line] = infra.prepare_base(base)
        self.assertIn(f'sudo install -d -o "$USER" {base}', line)
        self.assertFalse(base.parent.exists())


class TestForeignBase(unittest.TestCase):
    BASE = Path("/mnt/cache")

    @staticmethod
    def _bind(source: str, target: str) -> dict[str, object]:
        return {"Type": "bind", "Source": source, "Destination": target}

    def test_a_stopped_runner_binds_no_foreign_base(self) -> None:
        self.assertEqual(infra.foreign_base(self.BASE, None), [])

    def test_a_runner_on_the_same_base_passes(self) -> None:
        mounts = [
            self._bind("/sys/fs/cgroup", "/sys/fs/cgroup"),
            self._bind("/mnt/cache", "/mnt/cache"),
        ]
        self.assertEqual(infra.foreign_base(self.BASE, mounts), [])

    def test_a_runner_on_another_base_is_named(self) -> None:
        other = "/var/cache/infinito/core/cache"
        [line] = infra.foreign_base(self.BASE, [self._bind(other, other)])
        self.assertIn(other, line)
        self.assertIn(str(self.BASE), line)
        self.assertIn("make infra-down", line)

    def test_the_base_bound_elsewhere_or_as_a_volume_does_not_count(self) -> None:
        mounts = [
            self._bind("/mnt/cache", "/var/cache/infinito/core/cache"),
            {"Type": "volume", "Source": "/mnt/cache", "Destination": "/mnt/cache"},
        ]
        self.assertEqual(len(infra.foreign_base(self.BASE, mounts)), 1)


class TestLegacyRefusal(unittest.TestCase):
    def test_a_running_legacy_cache_is_refused_by_name(self) -> None:
        lines = infra.legacy_refusal("web\ninfinito-package-cache\ninfinito-coredns\n")
        self.assertEqual(len(lines), 1)
        self.assertIn("infinito-package-cache", lines[0])
        self.assertNotIn("infinito-registry-cache", lines[0])

    def test_every_legacy_cache_counts(self) -> None:
        for name in infra.LEGACY_CONTAINERS:
            with self.subTest(name=name):
                self.assertTrue(infra.legacy_refusal(f"{name}\n"))

    def test_without_a_legacy_cache_nothing_is_refused(self) -> None:
        self.assertEqual(
            infra.legacy_refusal("infinito-infra-runner\ninfinito-package-cache-old\n"),
            [],
        )

    def test_an_unanswered_host_is_refused(self) -> None:
        self.assertTrue(infra.legacy_refusal(None))

    def test_the_refusal_names_the_takeover(self) -> None:
        [line] = infra.legacy_refusal("infinito-registry-cache\n")
        self.assertIn("make infra-up takeover=true", line)


class TestLegacyRunning(unittest.TestCase):
    def test_every_running_legacy_cache_is_named(self) -> None:
        names = "web\ninfinito-package-cache\ninfinito-registry-cache\n"
        self.assertEqual(
            infra.legacy_running(names),
            ["infinito-registry-cache", "infinito-package-cache"],
        )

    def test_a_similar_name_is_no_legacy_cache(self) -> None:
        self.assertEqual(infra.legacy_running("infinito-package-cache-old\n"), [])


LEGACY = "infinito-nexus-core_default 172.30.0.6\n"
PROXY = "http://172.30.0.6:3128"


class TestProxyBridge(unittest.TestCase):
    def test_the_daemon_proxy_on_the_legacy_registry_is_taken_over(self) -> None:
        self.assertEqual(
            infra.proxy_bridge(f"{PROXY} {PROXY}", LEGACY),
            ("infinito-nexus-core_default", "172.30.0.6"),
        )

    def test_the_https_proxy_alone_counts(self) -> None:
        self.assertEqual(
            infra.proxy_bridge(f"{PROXY} ", LEGACY),
            ("infinito-nexus-core_default", "172.30.0.6"),
        )

    def test_another_address_on_the_legacy_network_needs_no_bridge(self) -> None:
        self.assertIsNone(infra.proxy_bridge("http://172.30.0.1:3128", LEGACY))

    def test_no_proxy_needs_no_bridge(self) -> None:
        self.assertIsNone(infra.proxy_bridge(" ", LEGACY))

    def test_a_proxy_by_name_needs_no_bridge(self) -> None:
        self.assertIsNone(
            infra.proxy_bridge("http://infinito-registry-cache:3128", LEGACY)
        )

    def test_a_stopped_legacy_registry_needs_no_bridge(self) -> None:
        self.assertIsNone(infra.proxy_bridge(PROXY, "infinito-nexus-core_default \n"))
        self.assertIsNone(infra.proxy_bridge(PROXY, ""))

    def test_the_runner_network_is_never_bridged(self) -> None:
        self.assertIsNone(
            infra.proxy_bridge("http://10.47.0.2:3128", "infinito-infra 10.47.0.2\n")
        )

    def test_a_missing_record_is_no_bridge(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        self.assertIsNone(infra.read_bridge(root / infra.BRIDGE_NAME))

    def test_a_record_holds_network_and_address(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / infra.BRIDGE_NAME).write_text("legacy-net 172.30.0.6\n")
        self.assertEqual(
            infra.read_bridge(root / infra.BRIDGE_NAME), ("legacy-net", "172.30.0.6")
        )

    def test_a_record_without_an_address_is_refused_loudly(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / infra.BRIDGE_NAME).write_text("legacy-net\n")
        with self.assertRaises(ValueError):
            infra.read_bridge(root / infra.BRIDGE_NAME)

    def test_the_override_joins_the_external_network_at_the_address(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        path = infra.write_bridge(root, "infinito-nexus-core_default", "172.30.0.6")
        override = load_yaml(root / path)
        self.assertEqual(
            override["services"][infra.SERVICE]["networks"],
            {infra.BRIDGE: {"ipv4_address": "172.30.0.6"}},
        )
        self.assertEqual(
            override["networks"][infra.BRIDGE],
            {"external": True, "name": "infinito-nexus-core_default"},
        )


class TestConcurrentUp(unittest.TestCase):
    def _race(self, lock_cm, synchronize_running: bool) -> int:
        started: list[int] = []
        state = {"running": False}
        gate = threading.Barrier(2)
        checked = threading.Barrier(2)

        def run(_argv: list[str]) -> None:
            started.append(1)
            state["running"] = True

        def running() -> bool:
            value = state["running"]
            if synchronize_running:
                checked.wait()
            return value

        def call() -> None:
            gate.wait()
            infra.up(
                ["compose"],
                refusal=list,
                foreign=list,
                running=running,
                run=run,
                lock=lock,
                base=lock.parent,
                recreate=False,
                takeover=[],
                bridge=None,
                installs=list,
                prepare=list,
                apply=list,
                evict=list,
            )

        with tempfile.TemporaryDirectory() as tmp, patch("builtins.print"):
            lock = Path(tmp) / "infra.lock"
            with patch.object(infra, "machine_lock", lock_cm):
                threads = [threading.Thread(target=call) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
        return len(started)

    def test_two_concurrent_calls_leave_one_runner(self) -> None:
        self.assertEqual(self._race(infra.machine_lock, synchronize_running=False), 1)

    def test_without_the_lock_both_would_start_one(self) -> None:
        self.assertEqual(
            self._race(lambda _path: nullcontext(), synchronize_running=True), 2
        )


class TestFloorRefusal(unittest.TestCase):
    def test_the_refusal_names_every_cap_variable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "INFINITO_CACHE_REGISTRY_HOST_PATH": f"{tmp}/r",
                "INFINITO_CACHE_PACKAGE_HOST_PATH": f"{tmp}/p",
                "INFINITO_CACHE_SHARED_HOST_PATH": f"{tmp}/s",
                "INFINITO_TOOLS_MODELS_HOST_PATH": f"{tmp}/m",
                "INFINITO_CACHE_REGISTRY_MAX_SIZE": "1t",
                "INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX": "1t",
                "INFINITO_CACHE_SHARED_MAX_SIZE": "1t",
                "INFINITO_TOOLS_MODELS_MAX_SIZE": "1t",
                "INFINITO_BUILD_CACHE_MAX_SIZE": "1t",
                "INFINITO_CACHE_MAX_IDLE_DAYS": "30",
                "INFINITO_CACHE_DISK_FLOOR": "15g",
            }
            with patch.object(infra, "free_bytes", return_value=0):
                lines = infra.floor_refusal(env, Usage(used=0, complete=True))
            with patch.object(infra, "free_bytes", return_value=10 * 1024**4):
                passed = infra.floor_refusal(env, Usage(used=0, complete=True))
        text = "\n".join(lines)
        for key in (
            "INFINITO_CACHE_REGISTRY_MAX_SIZE",
            "INFINITO_BUILD_CACHE_MAX_SIZE",
        ):
            self.assertIn(key, text)
        self.assertEqual(passed, [])


class TestStatus(unittest.TestCase):
    def test_the_gateway_url_is_on_loopback(self) -> None:
        state = infra.status(
            True,
            {
                "INFINITO_INFRA_SUBNET": "10.47.0.0/24",
                "INFINITO_TOOLS_TRANSLATE_PORT": "8101",
                "INFINITO_INFRA_RUNNER_CONTAINER": "runner-x",
            },
            {"ollama": True, "translate": False},
        )
        self.assertEqual(
            (state["address"], state["gateway"], state["container"]),
            ("10.47.0.2", "http://127.0.0.1:8101", "runner-x"),
        )
        self.assertEqual(
            state["tools_addressable"], {"ollama": True, "translate": False}
        )


class TestDeploy(unittest.TestCase):
    def test_the_cache_roles_deploy_inside_the_runner_from_the_checkout(self) -> None:
        commands = infra_inventory.deploy_commands(
            ["compose"],
            Path("/srv/core"),
            Path("/srv/core/inventories/development/infra.rendered.yml"),
            Path("/root/inventories/infinito-infra"),
            infra_inventory.CACHE_ROLES,
        )
        for command in commands:
            self.assertEqual(
                command[:8],
                [
                    "compose",
                    "exec",
                    "-T",
                    "-w",
                    "/srv/core",
                    "-e",
                    "PYTHONPATH=/srv/core",
                    "runner",
                ],
            )
        provision = next(
            c for c in commands if "cli.administration.inventory.provision" in c
        )
        included = provision[
            provision.index("--include") + 1 : provision.index("--vars-file")
        ]
        self.assertEqual(included, ["svc-registry-cache", "svc-cache-package"])
        self.assertIn("cli.administration.deploy.dedicated", commands[-1])

    def test_no_command_reinstalls_from_the_image_tree(self) -> None:
        commands = infra_inventory.deploy_commands(
            ["compose"],
            Path("/srv/core"),
            Path("/srv/core/inventories/development/infra.rendered.yml"),
            Path("/root/inventories/infinito-infra"),
            infra_inventory.CACHE_ROLES,
        )
        self.assertEqual(
            [c for c in commands if any("entry-bootstrap" in part for part in c)],
            [],
        )

    def test_the_deploy_never_builds_into_the_read_only_checkout(self) -> None:
        commands = infra_inventory.deploy_commands(
            ["compose"],
            Path("/srv/core"),
            Path("/srv/core/inventories/development/infra.rendered.yml"),
            Path("/root/inventories/infinito-infra"),
            infra_inventory.CACHE_ROLES,
        )
        self.assertIn("--skip-build", commands[-1])

    def test_a_checkout_outside_the_roots_is_not_visible(self) -> None:
        roots = [Path("/srv/core"), Path("/home/me/.local/share/worktrees")]
        self.assertTrue(
            infra.inside_roots(Path("/home/me/.local/share/worktrees/x"), roots)
        )
        self.assertFalse(infra.inside_roots(Path("/tmp/elsewhere"), roots))


_CACHE_ENV = {
    "INFINITO_CACHE_MAX_IDLE_DAYS": "30",
    "INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX": "20g",
    "INFINITO_CACHE_PACKAGE_HOST_PATH": "/c/package/data",
    "INFINITO_CACHE_PACKAGE_PORT": "8081",
    "INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR": "/c/package/frontend/ca",
    "INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR": "/c/package/frontend/certs",
    "INFINITO_CACHE_PACKAGE_FRONTEND_CONF": "/pins/upstreams.conf",
    "INFINITO_CACHE_REGISTRY_MAX_SIZE": "40g",
    "INFINITO_CACHE_REGISTRY_AUTH": "",
    "INFINITO_CACHE_REGISTRY_HOST_PATH": "/c/registry/mirror",
    "INFINITO_CACHE_REGISTRY_CA_HOST_PATH": "/c/registry/ca",
    "INFINITO_CACHE_REGISTRIES": "ghcr.io quay.io",
}
HLTH_RUNTIME_ROLE = "sys-ctl-hlth-runtime"


def _runtime_severity(applications: dict) -> dict:
    """Args:
        applications: the ``applications`` mapping of an inventory.

    Returns:
        The severity mapping the runtime scan applies after the inventory is
        merged over the role's own ``meta/services.yml``.
    """
    from plugins.filter.merge.with_defaults import merge_with_defaults
    from utils.cache.files import PROJECT_ROOT
    from utils.roles.mapping import ROLE_FILE_META_SERVICES

    services = load_yaml(
        PROJECT_ROOT / "roles" / HLTH_RUNTIME_ROLE / ROLE_FILE_META_SERVICES
    )
    merged = merge_with_defaults(
        {HLTH_RUNTIME_ROLE: {"services": services}},
        {HLTH_RUNTIME_ROLE: applications.get(HLTH_RUNTIME_ROLE, {})},
    )
    return merged[HLTH_RUNTIME_ROLE]["services"]["runtime"]["severity"]


class TestInventory(unittest.TestCase):
    def _render(self, env: dict[str, str]) -> dict:
        from utils.cache.files import PROJECT_ROOT, read_text
        from utils.cache.yaml import load_yaml

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / infra_inventory.INVENTORY_TEMPLATE
            template.parent.mkdir(parents=True)
            template.write_text(
                read_text(str(PROJECT_ROOT / infra_inventory.INVENTORY_TEMPLATE)),
                encoding="utf-8",
            )
            return load_yaml(infra_inventory.render_inventory(root, env))[
                "applications"
            ]

    def test_the_caches_take_their_caps_and_idle_window_from_the_environment(
        self,
    ) -> None:
        apps = self._render(_CACHE_ENV)
        package = apps["svc-cache-package"]["services"]["package"]
        self.assertEqual(
            (package["blobstore_max"], package["max_idle_days"]), ("20g", 30)
        )
        cache = apps["svc-registry-cache"]["services"]["cache"]
        self.assertEqual(
            (cache["max_idle_days"], cache["multi_proxy"]["max_size"]), (30, "40g")
        )

    def test_nexus_listens_on_the_port_the_host_tools_use(self) -> None:
        package = self._render(_CACHE_ENV)["svc-cache-package"]["services"]["package"]
        self.assertEqual(package["ports"]["local"]["http"], 8081)

    def test_the_registry_runs_as_multi_proxy_for_every_declared_registry(self) -> None:
        cache = self._render(_CACHE_ENV)["svc-registry-cache"]["services"]["cache"]
        self.assertEqual(cache["flavor"], "multi-proxy")
        self.assertEqual(cache["multi_proxy"]["registries"], ["ghcr.io", "quay.io"])
        self.assertEqual(cache["multi_proxy"]["auth"], "")

    def test_every_cache_byte_stays_at_the_dev_path(self) -> None:
        apps = self._render(_CACHE_ENV)
        cache = apps["svc-registry-cache"]["services"]["cache"]["multi_proxy"]
        services = apps["svc-cache-package"]["services"]
        self.assertEqual(
            (
                cache["mirror_path"],
                cache["ca_path"],
                services["package"]["data_path"],
                services["frontend"]["ca_path"],
                services["frontend"]["certs_path"],
            ),
            (
                "/c/registry/mirror",
                "/c/registry/ca",
                "/c/package/data",
                "/c/package/frontend/ca",
                "/c/package/frontend/certs",
            ),
        )
        self.assertEqual(
            services["frontend"]["ports"]["local"], {"http": 80, "https": 443}
        )

    def test_the_frontend_mounts_the_map_below_the_pin_root(self) -> None:
        frontend = self._render(_CACHE_ENV)["svc-cache-package"]["services"]["frontend"]
        self.assertEqual(frontend["map_path"], "/pins/upstreams.conf")

    def test_an_unset_pinned_map_is_refused(self) -> None:
        env = dict(_CACHE_ENV)
        del env["INFINITO_CACHE_PACKAGE_FRONTEND_CONF"]
        with self.assertRaises(KeyError):
            self._render(env)

    def test_a_changed_cap_changes_the_inventory(self) -> None:
        apps = self._render(
            {**_CACHE_ENV, "INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX": "5g"}
        )
        self.assertEqual(
            apps["svc-cache-package"]["services"]["package"]["blobstore_max"], "5g"
        )

    def test_an_unset_cap_is_refused(self) -> None:
        env = dict(_CACHE_ENV)
        del env["INFINITO_CACHE_REGISTRY_MAX_SIZE"]
        with self.assertRaises(KeyError):
            self._render(env)

    def test_the_runtime_scan_maps_severities_as_every_development_deploy(
        self,
    ) -> None:
        from cli.administration.deploy.development.common import (
            DEV_INVENTORY_VARS_FILE,
        )
        from utils.cache.files import PROJECT_ROOT

        development = load_yaml(PROJECT_ROOT / DEV_INVENTORY_VARS_FILE)
        severity = _runtime_severity(self._render(_CACHE_ENV))
        self.assertEqual(severity, _runtime_severity(development["applications"]))
        self.assertEqual(severity["CRITICAL"], "warn")

    def test_an_inventory_without_the_mapping_fails_on_a_critical_finding(
        self,
    ) -> None:
        self.assertEqual(_runtime_severity({})["CRITICAL"], "fail")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
