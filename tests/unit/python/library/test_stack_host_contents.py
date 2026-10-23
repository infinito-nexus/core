from __future__ import annotations

import importlib.util
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.testing import patch_module_args

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

sys.path.insert(0, str(PROJECT_ROOT))

MODULE_PATH = PROJECT_ROOT / "library" / "stack_host_contents.py"


def _load_stack_host_contents() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "library_stack_host_contents", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_stack_host_contents()


class WriteFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "redirect.conf"

    def tearDown(self):
        self._tmp.cleanup()

    def _module(self, *, check_mode=False):
        args = {"files": [], "mode": "0644", "_ansible_check_mode": check_mode}
        with patch_module_args(args):
            return AnsibleModule(
                argument_spec=_MOD.ARGUMENT_SPEC, supports_check_mode=True
            )

    def _write(self, content, *, check_mode=False):
        return _MOD.write_file(
            self._module(check_mode=check_mode), str(self.path), content, "0644"
        )

    def _mode(self):
        return stat.S_IMODE(self.path.stat().st_mode)

    def _content(self):
        return self.path.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read the file under test changes between reads

    def test_creates_missing_file_with_mode(self):
        self.assertTrue(self._write("server {}\n"))
        self.assertEqual(self._content(), "server {}\n")
        self.assertEqual(self._mode(), 0o644)

    def test_unchanged_content_reports_no_change(self):
        self._write("server {}\n")
        self.assertFalse(self._write("server {}\n"))

    def test_replaces_differing_content(self):
        self._write("server {}\n")
        self.assertTrue(self._write("server { listen 80; }\n"))
        self.assertEqual(self._content(), "server { listen 80; }\n")

    def test_repairs_mode_drift(self):
        self._write("server {}\n")
        self.path.chmod(0o600)
        self.assertTrue(self._write("server {}\n"))
        self.assertEqual(self._mode(), 0o644)

    def test_check_mode_reports_without_writing(self):
        self.assertTrue(self._write("server {}\n", check_mode=True))
        self.assertFalse(self.path.exists())
        self._write("server {}\n")
        self.assertTrue(self._write("other\n", check_mode=True))
        self.assertEqual(self._content(), "server {}\n")

    def test_leaves_no_staging_file_behind(self):
        self._write("server {}\n")
        self._write("other\n")
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])


if __name__ == "__main__":
    unittest.main()
