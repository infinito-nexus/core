"""Run roles/svc-bkp-nfs-2-local/files/script.sh against real tempdirs and
verify the differential snapshot semantics: a missing source SKIPs without
side effects, unchanged files are hard-linked between generations instead of
copied, changed files get their own inode, and deletions do not reach back
into older generations."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles" / "svc-bkp-nfs-2-local" / "files" / "script.sh"
REPO_NAME = "backup-nfs-to-local"


class NfsBackupScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.source = base / "export"
        self.backups = base / "backups"
        self.source.mkdir()
        self.backups.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, source=None, generation=None, exclude=None):
        env = os.environ.copy()
        if generation is not None:
            env["BKP_NFS_2_LOCAL_GENERATION"] = generation
        cmd = [
            "bash",
            str(SCRIPT),
            str(source or self.source),
            str(self.backups),
            REPO_NAME,
        ]
        if exclude is not None:
            cmd.append(exclude)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    def _generations(self):
        machine_dirs = list(self.backups.iterdir())
        self.assertEqual(len(machine_dirs), 1)
        repo_dir = machine_dirs[0] / REPO_NAME
        return sorted(repo_dir.iterdir())

    def test_missing_source_fails_loudly_without_side_effects(self):
        result = self._run(source=Path(self.tmp.name) / "does-not-exist")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR", result.stderr)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_first_run_creates_full_snapshot(self):
        (self.source / "a.txt").write_text("hello")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        generations = self._generations()
        self.assertEqual(len(generations), 1)
        content = (
            generations[0] / "files" / "a.txt"
        ).read_text()  # nocheck: cache-read tempdir fixture
        self.assertEqual(content, "hello")

    def test_second_run_hardlinks_unchanged_files(self):
        (self.source / "a.txt").write_text("hello")
        self.assertEqual(self._run(generation="20240101000000").returncode, 0)
        self.assertEqual(self._run(generation="20240101000001").returncode, 0)

        generations = self._generations()
        self.assertEqual(len(generations), 2)
        first = generations[0] / "files" / "a.txt"
        second = generations[1] / "files" / "a.txt"
        self.assertEqual(first.stat().st_ino, second.stat().st_ino)
        self.assertEqual(second.stat().st_nlink, 2)

    def test_changed_file_gets_own_inode_and_history_survives(self):
        changed = self.source / "a.txt"
        changed.write_text("v1")
        os.utime(changed, (1000000000, 1000000000))
        self.assertEqual(self._run(generation="20240101000000").returncode, 0)
        changed.write_text("v2")
        self.assertEqual(self._run(generation="20240101000001").returncode, 0)

        generations = self._generations()
        first = generations[0] / "files" / "a.txt"
        second = generations[1] / "files" / "a.txt"
        self.assertNotEqual(first.stat().st_ino, second.stat().st_ino)
        first_content = first.read_text()  # nocheck: cache-read tempdir fixture
        second_content = second.read_text()  # nocheck: cache-read tempdir fixture
        self.assertEqual(first_content, "v1")
        self.assertEqual(second_content, "v2")

    @unittest.skipIf(os.geteuid() == 0, "root reads past chmod 000")
    def test_failed_rsync_removes_incomplete_generation(self):
        secret = self.source / "unreadable.txt"
        secret.write_text("nope")
        secret.chmod(0o000)
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incomplete generation removed", result.stderr)
        machine_dirs = list(self.backups.iterdir())
        if machine_dirs:
            self.assertEqual(list((machine_dirs[0] / REPO_NAME).iterdir()), [])

    def test_exclude_is_anchored_and_survives_link_dest(self):
        shared = self.source / "infinito-state" / "backup" / "hash" / "repo"
        shared.mkdir(parents=True)
        (shared / "dump.sql").write_text("secret")
        decoy = self.source / "app" / "infinito-state" / "backup"
        decoy.mkdir(parents=True)
        (decoy / "decoy.txt").write_text("decoy")
        (self.source / "infinito-state" / "state.txt").write_text("state")

        exclude = "infinito-state/backup"
        self.assertEqual(
            self._run(generation="20240101000000", exclude=exclude).returncode, 0
        )
        self.assertEqual(
            self._run(generation="20240101000001", exclude=exclude).returncode, 0
        )

        for generation in self._generations():
            files = generation / "files"
            self.assertFalse((files / "infinito-state" / "backup").exists())
            self.assertTrue((files / "infinito-state" / "state.txt").is_file())
            self.assertTrue(
                (files / "app" / "infinito-state" / "backup" / "decoy.txt").is_file()
            )

    def test_deleted_file_vanishes_only_from_new_generation(self):
        (self.source / "keep.txt").write_text("keep")
        (self.source / "gone.txt").write_text("gone")
        self.assertEqual(self._run(generation="20240101000000").returncode, 0)
        (self.source / "gone.txt").unlink()
        self.assertEqual(self._run(generation="20240101000001").returncode, 0)

        generations = self._generations()
        self.assertTrue((generations[0] / "files" / "gone.txt").is_file())
        self.assertFalse((generations[1] / "files" / "gone.txt").exists())
        self.assertTrue((generations[1] / "files" / "keep.txt").is_file())


if __name__ == "__main__":
    unittest.main()
