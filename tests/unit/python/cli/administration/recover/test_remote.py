"""Unit tests for cli.administration.recover.remote (host + device sources)."""

from __future__ import annotations

import contextlib
import io
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.recover import remote
from cli.administration.recover import stage as recover_stage

LOCAL_STAGE = Path("/stage/local")
REMOTE_STAGE = "/tmp/tmp.Remote12345"


class SplitHostTest(unittest.TestCase):
    def test_splits_at_first_colon(self):
        self.assertEqual(
            remote.split_host("user@host:/dev/sdb1:usb"), ("user@host", "/dev/sdb1:usb")
        )


class RerootTest(unittest.TestCase):
    def test_keeps_relative_segments_drops_absolute_appends_root(self):
        self.assertEqual(
            remote._reroot(
                "/dev/sdb1:usb:20260710153000:/old", "/dev/sdb1", "/tmp/new"
            ),
            "/dev/sdb1:usb:20260710153000:/tmp/new",
        )


class CommandsTest(unittest.TestCase):
    def _commands(self, source: str, *, passphrase_stdin: bool):
        return remote.commands(
            source,
            local_stage=LOCAL_STAGE,
            remote_stage=REMOTE_STAGE,
            service_backup=True,
            passphrase_stdin=passphrase_stdin,
        )

    def test_block_device_uses_ssh_then_pull(self):
        steps, root = self._commands("user@host:/dev/sdb1:usb", passphrase_stdin=False)
        self.assertEqual(root, LOCAL_STAGE / recover_stage.TREE)
        self.assertEqual(steps[0][:2], ["ssh", "user@host"])
        self.assertIn(f"{REMOTE_STAGE}/{recover_stage.TREE}", steps[0][2])
        self.assertEqual(steps[1][0], "rsync")
        self.assertIn(f"user@host:{REMOTE_STAGE}/{recover_stage.TREE}/", steps[1])
        self.assertEqual(steps[1][-1], f"{root}/")

    def test_image_pulls_then_recovers_locally(self):
        steps, root = self._commands("host:/backup/usb.img", passphrase_stdin=True)
        image = str(LOCAL_STAGE / remote.IMAGE)
        self.assertEqual(root, LOCAL_STAGE / recover_stage.TREE)
        self.assertEqual(steps[0], ["rsync", "-a", "host:/backup/usb.img", image])
        self.assertEqual(steps[1][0], sys.executable)
        self.assertIn(image, steps[1])
        self.assertIn(str(root), steps[1])
        self.assertIn("--passphrase-stdin", steps[1])

    def test_no_step_names_a_fixed_tmp_path(self):
        for source in ("user@host:/dev/sdb1:usb", "host:/backup/usb.img"):
            with self.subTest(source=source):
                steps, _root = self._commands(source, passphrase_stdin=True)
                self.assertNotIn("/tmp/infinito-recover", " ".join(map(str, steps)))


class HostStageTest(unittest.TestCase):
    SOURCE = "root@srchost:/dev/sdb1:usb"

    def _run(
        self,
        *,
        mktemp: tuple[int, str, str] = (0, f"{REMOTE_STAGE}\n", ""),
        step: object = 0,
    ):
        calls: list[list[str]] = []
        self.calls = calls
        self.stdin_of: dict[str, object] = {}
        self.stderr = io.StringIO()

        def fake_run(cmd, check, **kwargs):
            calls.append(cmd)
            if cmd[2:] == ["mktemp", "-d"]:
                self.stdin_of["mktemp"] = kwargs.get("stdin")
                return subprocess.CompletedProcess(cmd, *mktemp)
            if cmd[:3] == ["ssh", "root@srchost", "rm"]:
                self.stdin_of["rm"] = kwargs.get("stdin")
                return subprocess.CompletedProcess(cmd, 0)
            if cmd[0] == "ssh":
                self.stdin_of["recover"] = kwargs.get("stdin")
            if isinstance(step, BaseException):
                raise step
            return subprocess.CompletedProcess(cmd, step)

        with (
            patch.object(remote.subprocess, "run", side_effect=fake_run),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(self.stderr),
        ):
            result = remote.run(
                self.SOURCE,
                local_stage=LOCAL_STAGE,
                preview=False,
                service_backup=True,
                passphrase_stdin=True,
            )
        return result, calls

    def test_only_the_recover_step_may_read_the_piped_passphrase(self):
        self._run()
        self.assertIs(self.stdin_of["mktemp"], subprocess.DEVNULL)
        self.assertIs(self.stdin_of["rm"], subprocess.DEVNULL)
        self.assertIsNone(self.stdin_of["recover"])

    def test_a_failed_mktemp_names_what_ssh_said(self):
        self._run(mktemp=(255, "", "Host key verification failed.\n"))
        self.assertIn("Host key verification failed.", self.stderr.getvalue())

    def test_an_interrupt_after_mktemp_still_removes_the_host_dir(self):
        with self.assertRaises(KeyboardInterrupt):
            self._run(step=KeyboardInterrupt())
        self.assertEqual(
            self.calls[-1], ["ssh", "root@srchost", "rm", "-rf", "--", REMOTE_STAGE]
        )

    def test_a_failed_mktemp_removes_nothing_on_the_host(self):
        self._run(mktemp=(255, "", "Connection refused\n"))
        self.assertEqual(self.calls, [["ssh", "root@srchost", "mktemp", "-d"]])

    def test_the_host_dir_is_created_first_and_removed_last(self):
        (returncode, root), calls = self._run()
        self.assertEqual((returncode, root), (0, LOCAL_STAGE / recover_stage.TREE))
        self.assertEqual(calls[0], ["ssh", "root@srchost", "mktemp", "-d"])
        self.assertEqual(
            calls[-1], ["ssh", "root@srchost", "rm", "-rf", "--", REMOTE_STAGE]
        )

    def test_the_host_dir_is_removed_when_a_step_fails(self):
        (returncode, root), calls = self._run(step=1)
        self.assertEqual((returncode, root), (1, None))
        self.assertEqual(
            calls[-1], ["ssh", "root@srchost", "rm", "-rf", "--", REMOTE_STAGE]
        )

    def test_no_recovery_runs_without_a_usable_host_dir(self):
        for mktemp in (
            (1, "", ""),
            (0, "/\n", ""),
            (0, "/tmp/../etc\n", ""),
            (0, "tmp.x\n", ""),
        ):
            with self.subTest(mktemp=mktemp):
                (returncode, root), calls = self._run(mktemp=mktemp)
                self.assertEqual((returncode, root), (2, None))
                self.assertEqual(calls, [["ssh", "root@srchost", "mktemp", "-d"]])

    def test_a_preview_runs_nothing(self):
        with (
            patch.object(remote.subprocess, "run", side_effect=AssertionError),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = remote.run(
                self.SOURCE,
                local_stage=LOCAL_STAGE,
                preview=True,
                service_backup=True,
                passphrase_stdin=True,
            )
        self.assertEqual(result, (0, LOCAL_STAGE / recover_stage.TREE))


class RunKeptTest(unittest.TestCase):
    def _run_kept(self, *, rsync_rc: int = 0) -> tuple[int, dict, str]:
        seen: dict = {}

        def fake_run(cmd, check, **kwargs):
            if cmd[0] == "rsync":
                image = Path(cmd[-1])
                if not image.parent.name.startswith(remote.STAGE_PREFIX):
                    raise AssertionError(f"image lands outside a private stage: {cmd}")
                seen["stage"] = image.parent
                seen["stage_mode"] = stat.S_IMODE(image.parent.stat().st_mode)
                image.write_bytes(b"LUKS")
            return subprocess.CompletedProcess(
                cmd, rsync_rc if cmd[0] == "rsync" else 0
            )

        out = io.StringIO()
        with (
            patch.object(remote.subprocess, "run", side_effect=fake_run),
            contextlib.redirect_stdout(out),
        ):
            returncode = remote.run_kept(
                "host:/backup/usb.img",
                preview=False,
                service_backup=True,
                passphrase_stdin=True,
            )
        return returncode, seen, out.getvalue()

    def test_a_successful_run_keeps_the_tree_and_names_it(self):
        returncode, seen, out = self._run_kept()
        try:
            self.assertEqual(returncode, 0)
            self.assertEqual(seen["stage_mode"], 0o700)
            self.assertEqual(seen["stage"].parent, Path(tempfile.gettempdir()))
            self.assertTrue(seen["stage"].name.startswith(remote.STAGE_PREFIX))
            self.assertIn(str(seen["stage"] / recover_stage.TREE), out)
            self.assertTrue(seen["stage"].is_dir())
        finally:
            recover_stage.remove(seen["stage"])

    def test_only_the_tree_is_kept_not_the_image(self):
        _returncode, seen, _out = self._run_kept()
        try:
            self.assertFalse((seen["stage"] / remote.IMAGE).exists())
        finally:
            recover_stage.remove(seen["stage"])

    def test_a_failed_run_removes_the_stage(self):
        returncode, seen, _out = self._run_kept(rsync_rc=23)
        self.assertEqual(returncode, 23)
        self.assertFalse(seen["stage"].exists())

    def test_a_raising_run_removes_the_stage(self):
        stages: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def tracked(*args, **kwargs):
            directory = real_mkdtemp(*args, **kwargs)
            stages.append(Path(directory))
            return directory

        with (
            patch.object(remote.tempfile, "mkdtemp", side_effect=tracked),
            patch.object(remote.subprocess, "run", side_effect=KeyboardInterrupt),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(KeyboardInterrupt),
        ):
            remote.run_kept(
                "host:/backup/usb.img",
                preview=False,
                service_backup=True,
                passphrase_stdin=True,
            )
        self.assertEqual(len(stages), 1)
        self.assertFalse(stages[0].exists())


if __name__ == "__main__":
    unittest.main()
