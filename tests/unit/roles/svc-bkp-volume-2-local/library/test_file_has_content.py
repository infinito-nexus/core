from __future__ import annotations

import contextlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import PROJECT_ROOT


class _ExitJsonError(Exception):
    def __init__(self, payload: dict):
        super().__init__("exit_json called")
        self.payload = payload


class _FailJsonError(Exception):
    def __init__(self, payload: dict):
        super().__init__("fail_json called")
        self.payload = payload


class FakeAnsibleModule:
    """
    Minimal stand-in for ansible.module_utils.basic.AnsibleModule,
    capturing exit_json/fail_json payloads.
    """

    def __init__(self, argument_spec=None, supports_check_mode=False, *, params=None):
        self.argument_spec = argument_spec or {}
        self.supports_check_mode = supports_check_mode
        self.params = params or {}

    def exit_json(self, **kwargs):
        raise _ExitJsonError(kwargs)

    def fail_json(self, **kwargs):
        raise _FailJsonError(kwargs)


def _import_module_under_test():
    """
    Load the module under test via file path computed by walking parents only.

    Repo root is ``parents[5]`` from this test file's location.
    """
    module_path = (
        PROJECT_ROOT
        / "roles"
        / "svc-bkp-volume-2-local"
        / "library"
        / "file_has_content.py"
    )
    if not module_path.is_file():
        raise RuntimeError(f"Module file not found at expected path: {module_path}")

    spec = importlib.util.spec_from_file_location(
        "svc_bkp_volume_2_local_file_has_content",
        str(module_path),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create import spec for: {module_path}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestFileHasContentModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _import_module_under_test()

    def _run_with_path(self, path: str) -> dict:
        fake = FakeAnsibleModule(params={"path": path})
        with patch.object(self.mod, "AnsibleModule", return_value=fake):
            try:
                self.mod.run_module()
            except _ExitJsonError as e:
                return e.payload
            except _FailJsonError as e:
                raise AssertionError(
                    f"Expected exit_json, got fail_json: {e.payload}"
                ) from e
        raise AssertionError("Expected module to call exit_json")

    def _run_expect_fail(self, path: str) -> dict:
        fake = FakeAnsibleModule(params={"path": path})
        with patch.object(self.mod, "AnsibleModule", return_value=fake):
            try:
                self.mod.run_module()
            except _FailJsonError as e:
                return e.payload
            except _ExitJsonError as e:
                raise AssertionError(
                    f"Expected fail_json, got exit_json: {e.payload}"
                ) from e
        raise AssertionError("Expected module to call fail_json")

    def test_missing_file_fails(self):
        missing = "/tmp/this-file-should-not-exist-ansible-test-12345"
        # Already-absent is the state this test requires; either way we proceed.
        with contextlib.suppress(FileNotFoundError):
            Path(missing).unlink()

        payload = self._run_expect_fail(missing)

        self.assertIn("msg", payload)
        self.assertIn("does not exist", payload["msg"])
        self.assertFalse(payload.get("changed", True))
        self.assertFalse(payload.get("exists", True))
        self.assertFalse(payload.get("has_content", True))
        self.assertEqual(payload.get("size", -1), 0)

    def test_directory_path_fails(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self._run_expect_fail(td)

        self.assertIn("msg", payload)
        self.assertIn("not a file", payload["msg"])

    def test_empty_file_exists_but_has_no_content(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "databases.csv"
            p.write_text("", encoding="utf-8")

            payload = self._run_with_path(str(p))

        self.assertTrue(payload["exists"])
        self.assertFalse(payload["has_content"])
        self.assertEqual(payload["size"], 0)
        self.assertFalse(payload["changed"])

    def test_whitespace_only_file_has_no_content_but_nonzero_size(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "databases.csv"
            p.write_text("   \n\t  \n", encoding="utf-8")

            payload = self._run_with_path(str(p))

        self.assertTrue(payload["exists"])
        self.assertFalse(payload["has_content"])
        self.assertGreater(payload["size"], 0)

    def test_nonempty_file_has_content_true(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "databases.csv"
            p.write_text("db1,postgres,user,pass\n", encoding="utf-8")

            payload = self._run_with_path(str(p))

        self.assertTrue(payload["exists"])
        self.assertTrue(payload["has_content"])
        self.assertGreater(payload["size"], 0)


if __name__ == "__main__":
    unittest.main()
