from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.testing import patch_module_args

from utils.directory_batch import ensure_all


def _entry(path, mode="0755"):
    return {"path": str(path), "mode": mode, "owner": None, "group": None}


class EnsureAllTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _ensure(self, entries, *, check_mode=False):
        with patch_module_args({"_ansible_check_mode": check_mode}):
            module = AnsibleModule(argument_spec={}, supports_check_mode=True)
            return ensure_all(module, entries)

    def test_returns_the_changed_paths_in_order_with_one_diff_each(self):
        first = self.root / "a"
        second = self.root / "b"
        changed_paths, diffs = self._ensure([_entry(first), _entry(second)])
        self.assertEqual(changed_paths, [str(first), str(second)])
        self.assertEqual(
            [diff["after"]["path"] for diff in diffs], [str(first), str(second)]
        )

    def test_unchanged_paths_are_left_out(self):
        existing = self.root / "kept"
        existing.mkdir()
        existing.chmod(0o755)
        self.assertEqual(self._ensure([_entry(existing)]), ([], []))

    def test_empty_entries_change_nothing(self):
        self.assertEqual(self._ensure([]), ([], []))

    def test_check_mode_reports_without_creating(self):
        target = self.root / "new"
        changed_paths, _ = self._ensure([_entry(target)], check_mode=True)
        self.assertEqual(changed_paths, [str(target)])
        self.assertFalse(target.exists())

    def test_first_error_fails_with_the_paths_changed_before_it(self):
        created = self.root / "created"
        blocker = self.root / "blocker"
        never = self.root / "never"
        blocker.write_text("", encoding="utf-8")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit):
            self._ensure([_entry(created), _entry(blocker), _entry(never)])
        result = json.loads(buffer.getvalue())
        self.assertTrue(result["failed"])
        self.assertEqual(result["path"], str(blocker))
        self.assertEqual(result["changed_paths"], [str(created)])
        self.assertFalse(never.exists())


if __name__ == "__main__":
    unittest.main()
