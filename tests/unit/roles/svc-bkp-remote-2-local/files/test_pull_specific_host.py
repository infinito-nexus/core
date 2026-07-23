import os
import subprocess
import types
import unittest
from unittest.mock import patch

from utils.cache.files import read_text

from . import PROJECT_ROOT


def load_module():
    """
    Dynamically load the target script:
    roles/svc-bkp-remote-2-local/files/pull_specific_host.py
    relative to this test file.
    """
    target_path = (
        PROJECT_ROOT
        / "roles"
        / "svc-bkp-remote-2-local"
        / "files"
        / "pull_specific_host.py"
    )
    if not target_path.exists():
        raise FileNotFoundError(f"Cannot find script at {target_path}")
    spec = types.ModuleType("pull_specific_host_module")
    code = read_text(str(target_path))
    exec(compile(code, str(target_path), "exec"), spec.__dict__)
    return spec


class PullSpecificHostTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.hash64 = "a" * 64
        self.host = "1.2.3.4"
        self.remote = f"backup@{self.host}"
        self.ssh = f'ssh {self.mod.SSH_OPTS} "{self.remote}"'

        self.backups_dir = os.environ["INFINITO_DIR_BACKUPS"]
        self.base = f"{self.backups_dir}/{self.hash64}/"

        self.backup_type = "backup-docker-to-local"
        self.type_dir = f"{self.base}{self.backup_type}/"

        self.last_local = f"{self.type_dir}20250101000000"
        self.last_remote = f"{self.type_dir}20250202000000"

    def _completed(self, stdout="", returncode=0):
        return subprocess.CompletedProcess(
            args="mock", returncode=returncode, stdout=stdout, stderr=""
        )

    def _run_side_effect_success(
        self, command, capture_output=True, shell=True, text=True, check=True
    ):
        cmd = command if isinstance(command, str) else " ".join(command)

        if cmd.startswith(f"{self.ssh} sha256sum /etc/machine-id"):
            return self._completed(stdout=f"{self.hash64}  /etc/machine-id\n")

        if cmd.startswith(
            f'{self.ssh} "find {self.base} -maxdepth 1 -type d -execdir basename {{}} ;"'
        ):
            return self._completed(stdout=f"{self.hash64}\n{self.backup_type}\n")

        if cmd.startswith(f"ls -d {self.type_dir}* | tail -1"):
            return self._completed(stdout=self.last_local)

        if cmd.startswith(
            f'{self.ssh} "ls -d {self.backups_dir}/{self.hash64}/{self.backup_type}/*"'
        ):
            return self._completed(stdout=f"{self.last_remote}\n")

        return self._completed(stdout="")

    def _run_side_effect_find_fail(
        self, command, capture_output=True, shell=True, text=True, check=True
    ):
        cmd = command if isinstance(command, str) else " ".join(command)

        if cmd.startswith(
            f'{self.ssh} "find {self.base} -maxdepth 1 -type d -execdir basename {{}} ;"'
        ):
            raise subprocess.CalledProcessError(
                returncode=1, cmd=cmd, output="", stderr="find: error"
            )

        if cmd.startswith(f"{self.ssh} sha256sum /etc/machine-id"):
            return self._completed(stdout=f"{self.hash64}  /etc/machine-id\n")

        return self._completed(stdout="")

    def _run_side_effect_no_types(
        self, command, capture_output=True, shell=True, text=True, check=True
    ):
        cmd = command if isinstance(command, str) else " ".join(command)

        if cmd.startswith(f"{self.ssh} sha256sum /etc/machine-id"):
            return self._completed(stdout=f"{self.hash64}  /etc/machine-id\n")

        if cmd.startswith(
            f'{self.ssh} "find {self.base} -maxdepth 1 -type d -execdir basename {{}} ;"'
        ):
            return self._completed(stdout="")

        return self._completed(stdout="")

    def _run_side_effect_no_remote_versions(
        self, command, capture_output=True, shell=True, text=True, check=True
    ):
        """
        Like success, but remote versions are empty -> should raise RuntimeError
        """
        cmd = command if isinstance(command, str) else " ".join(command)

        if cmd.startswith(f"{self.ssh} sha256sum /etc/machine-id"):
            return self._completed(stdout=f"{self.hash64}  /etc/machine-id\n")

        if cmd.startswith(
            f'{self.ssh} "find {self.base} -maxdepth 1 -type d -execdir basename {{}} ;"'
        ):
            return self._completed(stdout=f"{self.hash64}\n{self.backup_type}\n")

        if cmd.startswith(f"ls -d {self.type_dir}* | tail -1"):
            return self._completed(stdout=self.last_local)

        if cmd.startswith(
            f'{self.ssh} "ls -d {self.backups_dir}/{self.hash64}/{self.backup_type}/*"'
        ):
            return self._completed(stdout="")

        return self._completed(stdout="")

    @patch("time.sleep", new=lambda *a, **k: None)
    @patch("pathlib.Path.mkdir")
    @patch.object(os, "system")
    @patch.object(subprocess, "run")
    def test_success_rsync_zero_exit(self, mock_run, mock_system, _mkd):
        mock_run.side_effect = self._run_side_effect_success
        mock_system.return_value = 0

        self.mod.pull_backups(self.host, self.backups_dir)

        self.assertTrue(mock_system.called, "rsync (os.system) should be called")

    @patch("time.sleep", new=lambda *a, **k: None)
    @patch("pathlib.Path.mkdir")
    @patch.object(os, "system")
    @patch.object(subprocess, "run")
    def test_no_backup_types_exit_zero(self, mock_run, mock_system, _mkd):
        mock_run.side_effect = self._run_side_effect_no_types
        mock_system.return_value = 0

        self.mod.pull_backups(self.host, self.backups_dir)

        self.assertFalse(
            mock_system.called, "rsync should not be called when no types found"
        )

    @patch("time.sleep", new=lambda *a, **k: None)
    @patch("pathlib.Path.mkdir")
    @patch.object(os, "system")
    @patch.object(subprocess, "run")
    def test_find_failure_raises_called_process_error(
        self, mock_run, mock_system, _mkd
    ):
        mock_run.side_effect = self._run_side_effect_find_fail
        mock_system.return_value = 0

        with self.assertRaises(subprocess.CalledProcessError):
            self.mod.pull_backups(self.host, self.backups_dir)

        self.assertFalse(
            mock_system.called, "rsync should not be called when find fails"
        )

    @patch("time.sleep", new=lambda *a, **k: None)
    @patch("pathlib.Path.mkdir")
    @patch.object(os, "system")
    @patch.object(subprocess, "run")
    def test_rsync_fails_after_retries_raises_runtime_error(
        self, mock_run, mock_system, _mkd
    ):
        mock_run.side_effect = self._run_side_effect_success
        mock_system.side_effect = [1] * 12

        with self.assertRaises(RuntimeError):
            self.mod.pull_backups(self.host, self.backups_dir)

        self.assertEqual(
            mock_system.call_count, 12, "rsync should have retried 12 times"
        )

    @patch("time.sleep", new=lambda *a, **k: None)
    @patch("pathlib.Path.mkdir")
    @patch.object(os, "system")
    @patch.object(subprocess, "run")
    def test_no_remote_backups_raises_runtime_error(self, mock_run, mock_system, _mkd):
        mock_run.side_effect = self._run_side_effect_no_remote_versions
        mock_system.return_value = 0

        with self.assertRaises(RuntimeError) as cm:
            self.mod.pull_backups(self.host, self.backups_dir)

        self.assertIn("No remote backups found", str(cm.exception))
        self.assertFalse(
            mock_system.called,
            "rsync should not be called when no remote backups exist",
        )


if __name__ == "__main__":
    unittest.main()
