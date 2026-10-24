from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from ansible.module_utils.testing import patch_module_args

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

sys.path.insert(0, str(PROJECT_ROOT))

MODULE_PATH = PROJECT_ROOT / "library" / "directory_batch.py"


def _load_directory_batch() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "library_directory_batch", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_directory_batch()


class DirectoryBatchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        for path in self.root.rglob("*"):  # nocheck: project-walk
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o700)
        self._tmp.cleanup()

    def _run(self, args, *, check_mode=False, diff=False):
        buffer = io.StringIO()
        module_args = {**args, "_ansible_check_mode": check_mode, "_ansible_diff": diff}
        with (
            patch_module_args(module_args),
            contextlib.redirect_stdout(buffer),
            self.assertRaises(SystemExit),
        ):
            _MOD.main()
        return json.loads(buffer.getvalue())

    def _path(self, *parts):
        return str(self.root.joinpath(*parts))

    def _mode(self, path):
        return stat.S_IMODE(Path(path).stat().st_mode)

    def _mkdir(self, path, mode):
        Path(path).mkdir()
        Path(path).chmod(mode)

    def test_creates_missing_directory_with_its_mode(self):
        target = self._path("cache")
        result = self._run({"entries": [{"path": target, "mode": "0700"}]})
        self.assertTrue(result["changed"])
        self.assertEqual(result["changed_paths"], [target])
        self.assertEqual(self._mode(target), 0o700)

    def test_missing_parents_receive_the_same_mode(self):
        target = self._path("a", "b", "c")
        self._run({"entries": [{"path": target, "mode": "0750"}]})
        self.assertEqual(self._mode(self._path("a")), 0o750)
        self.assertEqual(self._mode(self._path("a", "b")), 0o750)
        self.assertEqual(self._mode(target), 0o750)

    def test_existing_parent_keeps_its_mode(self):
        self._mkdir(self._path("a"), 0o701)
        self._run({"entries": [{"path": self._path("a", "b"), "mode": "0755"}]})
        self.assertEqual(self._mode(self._path("a")), 0o701)

    def test_existing_directory_with_same_mode_is_unchanged(self):
        target = self._path("conf.d")
        self._run({"entries": [{"path": target, "mode": "0755"}]})
        result = self._run({"entries": [{"path": target, "mode": "0755"}]})
        self.assertFalse(result["changed"])
        self.assertEqual(result["changed_paths"], [])

    def test_mode_drift_is_repaired_and_reported(self):
        target = self._path("conf.d")
        self._run({"entries": [{"path": target, "mode": "0755"}]})
        Path(target).chmod(0o700)
        result = self._run({"entries": [{"path": target, "mode": "0755"}]})
        self.assertEqual(result["changed_paths"], [target])
        self.assertEqual(self._mode(target), 0o755)

    def test_entry_without_mode_keeps_the_existing_mode(self):
        target = self._path("kept")
        self._mkdir(target, 0o701)
        result = self._run({"entries": [{"path": target}]})
        self.assertFalse(result["changed"])
        self.assertEqual(self._mode(target), 0o701)

    def test_only_the_drifted_entry_is_reported(self):
        same = self._path("same")
        drifted = self._path("drifted")
        entries = [{"path": same, "mode": "0755"}, {"path": drifted, "mode": "0755"}]
        self._run({"entries": entries})
        Path(drifted).chmod(0o700)
        self.assertEqual(self._run({"entries": entries})["changed_paths"], [drifted])

    def test_paths_share_the_top_level_mode(self):
        first = self._path("instance")
        second = self._path("instance", "volumes")
        result = self._run({"paths": [first, second], "mode": "0755"})
        self.assertEqual(result["changed_paths"], [first, second])
        self.assertEqual(self._mode(first), 0o755)
        self.assertEqual(self._mode(second), 0o755)

    def test_trailing_slash_path_is_created(self):
        target = self._path("servers") + "/"
        result = self._run({"paths": [target], "mode": "0755"})
        self.assertEqual(result["changed_paths"], [target])
        self.assertTrue(Path(target).is_dir())

    def test_empty_paths_change_nothing(self):
        result = self._run({"paths": [], "mode": "0755"})
        self.assertFalse(result["changed"])

    def test_check_mode_reports_missing_path_without_creating_it(self):
        target = self._path("new", "child")
        result = self._run({"paths": [target], "mode": "0755"}, check_mode=True)
        self.assertEqual(result["changed_paths"], [target])
        self.assertFalse(Path(self._path("new")).exists())

    def test_check_mode_reports_mode_drift_without_chmod(self):
        target = self._path("conf.d")
        self._mkdir(target, 0o700)
        result = self._run({"paths": [target], "mode": "0755"}, check_mode=True)
        self.assertEqual(result["changed_paths"], [target])
        self.assertEqual(self._mode(target), 0o700)

    def test_check_mode_reports_owner_drift_without_chown(self):
        target = self._path("owned")
        Path(target).mkdir()
        foreign_uid = str(Path(target).stat().st_uid + 1)
        result = self._run({"paths": [target], "owner": foreign_uid}, check_mode=True)
        self.assertEqual(result["changed_paths"], [target])
        self.assertEqual(Path(target).stat().st_uid, os.getuid())

    def test_current_owner_and_group_are_unchanged(self):
        target = self._path("owned")
        Path(target).mkdir()
        info = Path(target).stat()
        result = self._run(
            {
                "entries": [
                    {
                        "path": target,
                        "owner": str(info.st_uid),
                        "group": str(info.st_gid),
                    }
                ]
            }
        )
        self.assertFalse(result["changed"])

    def test_unknown_owner_fails_loudly(self):
        target = self._path("owned")
        Path(target).mkdir()
        result = self._run({"paths": [target], "owner": "no-such-user-dirbatch"})
        self.assertTrue(result["failed"])
        self.assertIn("no-such-user-dirbatch", result["msg"])

    def test_symlink_to_directory_is_followed(self):
        real = self._path("real")
        link = self._path("link")
        self._mkdir(real, 0o700)
        Path(link).symlink_to(real)
        result = self._run({"paths": [link], "mode": "0755"})
        self.assertEqual(result["changed_paths"], [link])
        self.assertEqual(self._mode(real), 0o755)
        self.assertTrue(Path(link).is_symlink())

    def test_existing_file_fails_loudly(self):
        target = self._path("nginx.conf")
        Path(target).write_text("events {}\n", encoding="utf-8")
        result = self._run({"paths": [target], "mode": "0755"})
        self.assertTrue(result["failed"])
        self.assertIn("already exists as a file", result["msg"])

    def test_relative_path_fails_loudly(self):
        result = self._run({"paths": ["relative/dir"], "mode": "0755"})
        self.assertTrue(result["failed"])
        self.assertIn("not an absolute path", result["msg"])

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_unwritable_parent_fails_loudly(self):
        parent = self._path("locked")
        self._mkdir(parent, 0o500)
        result = self._run({"paths": [self._path("locked", "child")], "mode": "0755"})
        self.assertTrue(result["failed"])
        self.assertIn("Could not create", result["msg"])

    def test_failure_reports_the_paths_changed_before_it(self):
        created = self._path("created")
        blocker = self._path("blocker")
        Path(blocker).write_text("", encoding="utf-8")
        result = self._run({"paths": [created, blocker], "mode": "0755"})
        self.assertTrue(result["failed"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["changed_paths"], [created])

    def test_entries_and_paths_are_mutually_exclusive(self):
        result = self._run(
            {"entries": [{"path": self._path("a")}], "paths": [self._path("b")]}
        )
        self.assertTrue(result["failed"])
        self.assertIn("mutually exclusive", result["msg"])

    def test_entries_and_top_level_mode_are_mutually_exclusive(self):
        result = self._run({"entries": [{"path": self._path("a")}], "mode": "0755"})
        self.assertTrue(result["failed"])
        self.assertIn("mutually exclusive", result["msg"])

    def test_entries_or_paths_is_required(self):
        result = self._run({"mode": "0755"})
        self.assertTrue(result["failed"])
        self.assertIn("one of the following is required", result["msg"])

    def test_unknown_entry_key_is_rejected(self):
        result = self._run({"entries": [{"path": self._path("a"), "recurse": True}]})
        self.assertTrue(result["failed"])
        self.assertIn("recurse", result["msg"])

    def test_diff_mode_lists_each_changed_path(self):
        target = self._path("conf.d")
        result = self._run({"paths": [target], "mode": "0755"}, diff=True)
        self.assertEqual(len(result["diff"]), 1)
        self.assertEqual(result["diff"][0]["before"]["state"], "absent")
        self.assertEqual(result["diff"][0]["after"]["state"], "directory")

    def test_diff_mode_records_the_mode_change(self):
        target = self._path("conf.d")
        self._mkdir(target, 0o700)
        result = self._run({"paths": [target], "mode": "0755"}, diff=True)
        self.assertEqual(result["diff"][0]["before"]["mode"], "0700")
        self.assertEqual(result["diff"][0]["after"]["mode"], "0755")

    def test_no_diff_outside_diff_mode(self):
        result = self._run({"paths": [self._path("conf.d")], "mode": "0755"})
        self.assertNotIn("diff", result)


if __name__ == "__main__":
    unittest.main()
