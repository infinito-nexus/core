import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

SPEC = importlib.util.spec_from_file_location(
    "code_settings", PROJECT_ROOT / "roles/dsk-code/files/python/code_settings.py"
)
code_settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(code_settings)

GUARD = {
    "search.ripgrep.maxThreads": 4,
    "files.watcherExclude": {
        "**/.worktrees/**": True,
        "**/.claude/worktrees/**": True,
    },
}


class CodeSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "Code - OSS/User/settings.json"

    def write(self, text):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(text)

    def read(self):
        return json.loads(self.path.read_text())  # nocheck: cache-read

    def test_guard_keeps_every_unrelated_setting(self):
        self.write(
            '{"editor.fontSize": 14, "files.watcherExclude": {"**/node_modules/**": true}}'
        )
        self.assertTrue(code_settings.apply(self.path, GUARD))
        self.assertEqual(
            self.read(),
            {
                "editor.fontSize": 14,
                "search.ripgrep.maxThreads": 4,
                "files.watcherExclude": {
                    "**/node_modules/**": True,
                    **GUARD["files.watcherExclude"],
                },
            },
        )

    def test_guard_replaces_a_weaker_value(self):
        self.write(
            '{"search.ripgrep.maxThreads": 12, '
            '"files.watcherExclude": {"**/.worktrees/**": false}}'
        )
        code_settings.apply(self.path, GUARD)
        self.assertEqual(self.read(), GUARD)

    def test_second_merge_leaves_the_file_untouched(self):
        self.write('{"editor.fontSize": 14}')
        code_settings.apply(self.path, GUARD)
        written = self.path.read_bytes()  # nocheck: cache-read
        self.assertFalse(code_settings.apply(self.path, GUARD))
        self.assertEqual(self.path.read_bytes(), written)  # nocheck: cache-read

    def test_settings_that_already_hold_the_guard_keep_their_comments(self):
        text = (
            "{\n  // own note\n"
            + json.dumps(GUARD)[1:-1]
            + ',\n  "editor.fontSize": 14,\n}\n'
        )
        self.write(text)
        self.assertFalse(code_settings.apply(self.path, GUARD))
        self.assertEqual(self.path.read_text(), text)  # nocheck: cache-read

    def test_missing_settings_file_is_created_owner_only(self):
        self.assertTrue(code_settings.apply(self.path, GUARD))
        self.assertEqual(self.read(), GUARD)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_existing_file_mode_is_kept(self):
        self.write("{}")
        self.path.chmod(0o644)
        code_settings.apply(self.path, GUARD)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)

    def test_symlinked_settings_stay_a_symlink_and_the_target_gets_the_guard(self):
        target = Path(self.temporary.name) / "dotfiles/settings.json"
        target.parent.mkdir()
        target.write_text('{"editor.fontSize": 14}')
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(target)
        self.assertTrue(code_settings.apply(self.path, GUARD))
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(
            json.loads(target.read_text()),  # nocheck: cache-read
            {"editor.fontSize": 14, **GUARD},
        )

    def test_a_blank_settings_file_takes_the_guard(self):
        self.write("\n")
        self.assertTrue(code_settings.apply(self.path, GUARD))
        self.assertEqual(self.read(), GUARD)

    def test_empty_guard_creates_no_file(self):
        self.assertFalse(code_settings.apply(self.path, {}))
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
