import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str) -> ModuleType:
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class TestComposePull(unittest.TestCase):
    def setUp(self) -> None:
        self.m = _load_module("roles/sys-svc-compose/files/pull.py", "compose_pull_mod")

    def test_run_cmd_returns_rc_and_split_streams(self) -> None:
        cwd = Path("/")
        env = {}

        class DummyProc:
            def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def fake_run(*args, **kwargs):
            return DummyProc(7, "hello\n", "warn: variable is not set\n")

        with patch.object(self.m.subprocess, "run", side_effect=fake_run):
            rc, out, err = self.m.run_cmd(["echo", "x"], cwd=cwd, env=env)

        self.assertEqual(rc, 7)
        self.assertEqual(out, "hello\n")
        self.assertEqual(err, "warn: variable is not set\n")

    def test_base_compose_cmd_delegates_to_wrapper(self) -> None:
        cmd = self.m.base_compose_cmd(project="p", cwd=Path("/x"))
        self.assertEqual(cmd[0], "/usr/bin/compose")
        self.assertIn("--chdir", cmd)
        self.assertIn("/x", cmd)
        self.assertIn("--project", cmd)
        self.assertIn("p", cmd)
        self.assertEqual(cmd[-1], "--")

    def test_has_buildable_services_true(self) -> None:
        config_out = """
services:
  app:
    build:
      context: .
    image: example/app
"""
        base_cmd = ["docker", "compose", "-p", "p", "-f", "a.yml"]
        with patch.object(self.m, "run_cmd", return_value=(0, config_out, "")):
            self.assertTrue(
                self.m.has_buildable_services(
                    base_cmd=base_cmd, cwd=Path("/tmp"), env={}
                )
            )

    def test_has_buildable_services_false(self) -> None:
        config_out = """
services:
  app:
    image: example/app
"""
        base_cmd = ["docker", "compose", "-p", "p", "-f", "a.yml"]
        with patch.object(self.m, "run_cmd", return_value=(0, config_out, "")):
            self.assertFalse(
                self.m.has_buildable_services(
                    base_cmd=base_cmd, cwd=Path("/tmp"), env={}
                )
            )

    def test_run_or_fail_success_does_not_raise(self) -> None:
        with patch.object(self.m, "run_cmd", return_value=(0, "ok\n", "")):
            self.m.run_or_fail(
                ["docker", "compose", "ps"], cwd=Path("/"), env={}, label="x"
            )

    def test_run_or_fail_failure_raises(self) -> None:
        with (
            patch.object(self.m, "run_cmd", return_value=(9, "", "boom\n")),
            self.assertRaises(RuntimeError) as ctx,
        ):
            self.m.run_or_fail(
                ["docker", "compose", "pull"], cwd=Path("/"), env={}, label="pull"
            )
        self.assertIn("pull failed", str(ctx.exception))

    def test_main_short_circuits_when_lock_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lock_dir = Path(td) / "locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            lock_key = "abc123"
            (lock_dir / f"{lock_key}.lock").write_text("ok\n", encoding="utf-8")

            argv = [
                "pull.py",
                "--chdir",
                td,
                "--project",
                "p",
                "--compose-files",
                "-f a.yml -f b.yml",
                "--lock-dir",
                str(lock_dir),
                "--lock-key",
                lock_key,
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(self.m, "run_or_fail") as rof_mock,
                patch.object(self.m, "has_buildable_services") as hbs_mock,
            ):
                rc = self.m.main()

            self.assertEqual(rc, 0)
            rof_mock.assert_not_called()
            hbs_mock.assert_not_called()

    def test_main_runs_build_and_pull_and_writes_lock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chdir = Path(td) / "instance"
            chdir.mkdir(parents=True, exist_ok=True)

            lock_dir = Path(td) / "locks"
            lock_key = "k1"

            argv = [
                "pull.py",
                "--chdir",
                str(chdir),
                "--project",
                "p",
                "--compose-files",
                "-f a.yml -f b.yml",
                "--env-file",
                "/x/.env",
                "--lock-dir",
                str(lock_dir),
                "--lock-key",
                lock_key,
                "--ignore-buildable",
            ]

            base_cmd = [
                "docker",
                "compose",
                "-p",
                "p",
                "-f",
                "a.yml",
                "-f",
                "b.yml",
                "--env-file",
                "/x/.env",
            ]

            calls: list[list[str]] = []

            def fake_run_cmd(
                cmd: list[str], *, cwd: Path, env: dict[str, str]
            ) -> tuple[int, str, str]:
                calls.append(cmd)
                if cmd[-2:] == ["pull", "--help"]:
                    return 0, "Usage:\n  --ignore-buildable\n", ""
                return 0, "", ""

            fallback_calls: list[list[str]] = []

            def fake_run_or_fail(
                cmd: list[str], *, cwd: Path, env: dict[str, str], label: str
            ) -> None:
                fallback_calls.append(cmd)

            with (
                patch.object(sys, "argv", argv),
                patch.object(self.m, "has_buildable_services", return_value=True),
                patch.object(self.m, "run_cmd", side_effect=fake_run_cmd),
                patch.object(self.m, "base_compose_cmd", return_value=base_cmd),
                patch.object(self.m, "run_or_fail", side_effect=fake_run_or_fail),
            ):
                rc = self.m.main()

            self.assertEqual(rc, 0)
            self.assertTrue(
                (lock_dir / f"{lock_key}.lock").exists(),
                "lock file should be written on success",
            )

            self.assertEqual(calls[0], [*base_cmd, "build", "--pull"])
            self.assertEqual(calls[1], [*base_cmd, "pull", "--help"])
            self.assertEqual(calls[2], [*base_cmd, "config"])
            self.assertEqual(calls[3], [*base_cmd, "pull", "--ignore-buildable"])
            self.assertEqual(fallback_calls, [])

    def test_main_falls_back_to_plain_build_when_build_pull_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chdir = Path(td) / "instance"
            chdir.mkdir(parents=True, exist_ok=True)

            lock_dir = Path(td) / "locks"
            lock_key = "kfb"

            argv = [
                "pull.py",
                "--chdir",
                str(chdir),
                "--project",
                "p",
                "--compose-files",
                "-f a.yml",
                "--lock-dir",
                str(lock_dir),
                "--lock-key",
                lock_key,
            ]

            base_cmd = ["docker", "compose", "-p", "p", "-f", "a.yml"]

            def fake_run_cmd(
                cmd: list[str], *, cwd: Path, env: dict[str, str]
            ) -> tuple[int, str, str]:
                if cmd[-2:] == ["build", "--pull"]:
                    return 1, "", "build --pull failed\n"
                return 0, "", ""

            fallback_calls: list[list[str]] = []

            def fake_run_or_fail(
                cmd: list[str], *, cwd: Path, env: dict[str, str], label: str
            ) -> None:
                fallback_calls.append(cmd)

            with (
                patch.object(sys, "argv", argv),
                patch.object(self.m, "has_buildable_services", return_value=True),
                patch.object(self.m, "run_cmd", side_effect=fake_run_cmd),
                patch.object(self.m, "base_compose_cmd", return_value=base_cmd),
                patch.object(self.m, "run_or_fail", side_effect=fake_run_or_fail),
            ):
                rc = self.m.main()

            self.assertEqual(rc, 0)
            self.assertEqual(fallback_calls, [[*base_cmd, "build"]])

    def test_main_pull_omits_ignore_buildable_when_not_supported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chdir = Path(td) / "instance"
            chdir.mkdir(parents=True, exist_ok=True)

            lock_dir = Path(td) / "locks"
            lock_key = "k2"

            argv = [
                "pull.py",
                "--chdir",
                str(chdir),
                "--project",
                "p",
                "--compose-files",
                "-f a.yml",
                "--lock-dir",
                str(lock_dir),
                "--lock-key",
                lock_key,
                "--ignore-buildable",
            ]

            base_cmd = ["docker", "compose", "-p", "p", "-f", "a.yml"]

            calls: list[list[str]] = []

            def fake_run_cmd(
                cmd: list[str], *, cwd: Path, env: dict[str, str]
            ) -> tuple[int, str, str]:
                calls.append(cmd)
                if cmd[-2:] == ["pull", "--help"]:
                    return 0, "Usage:\n", ""
                return 0, "", ""

            with (
                patch.object(sys, "argv", argv),
                patch.object(self.m, "has_buildable_services", return_value=False),
                patch.object(self.m, "run_cmd", side_effect=fake_run_cmd),
                patch.object(self.m, "base_compose_cmd", return_value=base_cmd),
            ):
                rc = self.m.main()

            self.assertEqual(rc, 0)
            self.assertEqual(calls[0], [*base_cmd, "pull", "--help"])
            self.assertEqual(calls[1], [*base_cmd, "config"])
            self.assertEqual(calls[2], [*base_cmd, "pull"])

    def test_main_tolerates_pull_failure_when_images_local(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chdir = Path(td) / "instance"
            chdir.mkdir(parents=True, exist_ok=True)

            lock_dir = Path(td) / "locks"
            lock_key = "ktol"

            argv = [
                "pull.py",
                "--chdir",
                str(chdir),
                "--project",
                "p",
                "--compose-files",
                "-f a.yml",
                "--lock-dir",
                str(lock_dir),
                "--lock-key",
                lock_key,
            ]

            base_cmd = ["docker", "compose", "-p", "p", "-f", "a.yml"]

            def fake_run_cmd(
                cmd: list[str], *, cwd: Path, env: dict[str, str]
            ) -> tuple[int, str, str]:
                if cmd[-1] == "pull":
                    return 1, "", "pull failed\n"
                if cmd[-2:] == ["config", "--images"]:
                    return 0, "image:1\nimage:2\n", ""
                if cmd[:3] == ["docker", "image", "inspect"]:
                    return 0, "", ""
                return 0, "", ""

            with (
                patch.object(sys, "argv", argv),
                patch.object(self.m, "has_buildable_services", return_value=False),
                patch.object(self.m, "run_cmd", side_effect=fake_run_cmd),
                patch.object(self.m, "base_compose_cmd", return_value=base_cmd),
            ):
                rc = self.m.main()

            self.assertEqual(rc, 0)
            self.assertTrue(
                (lock_dir / f"{lock_key}.lock").exists(),
                "lock should still be written when pull fails but images are local",
            )

    def test_main_raises_when_pull_fails_and_images_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chdir = Path(td) / "instance"
            chdir.mkdir(parents=True, exist_ok=True)

            lock_dir = Path(td) / "locks"
            lock_key = "kmiss"

            argv = [
                "pull.py",
                "--chdir",
                str(chdir),
                "--project",
                "p",
                "--compose-files",
                "-f a.yml",
                "--lock-dir",
                str(lock_dir),
                "--lock-key",
                lock_key,
            ]

            base_cmd = ["docker", "compose", "-p", "p", "-f", "a.yml"]

            def fake_run_cmd(
                cmd: list[str], *, cwd: Path, env: dict[str, str]
            ) -> tuple[int, str, str]:
                if cmd[-1] == "pull":
                    return 1, "", "pull failed\n"
                if cmd[-2:] == ["config", "--images"]:
                    return 0, "image:1\n", ""
                if cmd[:3] == ["docker", "image", "inspect"]:
                    return 1, "", "no such image\n"
                return 0, "", ""

            with (
                patch.object(sys, "argv", argv),
                patch.object(self.m, "has_buildable_services", return_value=False),
                patch.object(self.m, "run_cmd", side_effect=fake_run_cmd),
                patch.object(self.m, "base_compose_cmd", return_value=base_cmd),
                self.assertRaises(RuntimeError) as ctx,
            ):
                self.m.main()
            self.assertIn("missing locally", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
