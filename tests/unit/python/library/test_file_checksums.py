from __future__ import annotations

import hashlib
import importlib.util
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

MODULE_PATH = PROJECT_ROOT / "library" / "file_checksums.py"


def _load_file_checksums() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "library_file_checksums", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_file_checksums()


class PathStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        with patch_module_args({"paths": []}):
            self.module = AnsibleModule(
                argument_spec=_MOD.ARGUMENT_SPEC, supports_check_mode=True
            )

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self, path):
        return _MOD.path_state(self.module, str(path))

    def test_regular_file_reports_sha1_and_mode(self):
        target = self.root / "icon.png"
        target.write_bytes(b"png")
        target.chmod(0o640)

        state = self._state(target)

        self.assertEqual(
            state,
            {
                "isreg": True,
                "mode": "0640",
                "checksum": hashlib.sha1(b"png").hexdigest(),  # noqa: S324 - the checksum Ansible copy compares is SHA-1
            },
        )

    def test_missing_path_is_not_regular(self):
        self.assertEqual(
            self._state(self.root / "absent"),
            {"isreg": False, "mode": None, "checksum": None},
        )

    def test_directory_is_not_regular(self):
        (self.root / "nested").mkdir()

        self.assertFalse(self._state(self.root / "nested")["isreg"])

    def test_symlink_is_reported_not_followed(self):
        target = self.root / "real"
        target.write_bytes(b"data")
        (self.root / "link").symlink_to(target)

        self.assertFalse(self._state(self.root / "link")["isreg"])

    def test_path_below_a_file_is_not_regular(self):
        (self.root / "file").write_bytes(b"x")

        self.assertFalse(self._state(self.root / "file" / "child")["isreg"])


if __name__ == "__main__":
    unittest.main()
