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
import unittest.mock as mock
from pathlib import Path
from typing import TYPE_CHECKING

from ansible.module_utils.testing import patch_module_args

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

sys.path.insert(0, str(PROJECT_ROOT))

from utils import directory_batch

MODULE_PATH = (
    PROJECT_ROOT
    / "roles"
    / "sys-svc-compose"
    / "library"
    / "compose_instance_prepare.py"
)

FAKE_COMPOSE = """#!/bin/sh
pwd -P > "{record}"
printf '%s\\n' "$@" >> "{record}"
printf '{stdout}'
printf '{stderr}' >&2
exit {rc}
"""


def _load_module() -> ModuleType:
    sys.modules.setdefault("ansible.module_utils.directory_batch", directory_batch)
    spec = importlib.util.spec_from_file_location(
        "sys_svc_compose_compose_instance_prepare", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_module()


class ComposeInstancePrepareTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.record = self.root / "compose.record"
        self.instance = self.root / "compose" / "app"
        self.marker = self.instance / ".compose-up-pending"
        self._fake_compose(stdout="", stderr="", rc=0)

    def tearDown(self):
        self._tmp.cleanup()

    def _fake_compose(self, *, stdout, stderr, rc):
        script = self.bin / "compose"
        script.write_text(
            FAKE_COMPOSE.format(
                record=self.record, stdout=stdout, stderr=stderr, rc=rc
            ),
            encoding="utf-8",
        )
        script.chmod(0o755)

    def _args(self, **overrides):
        args = {
            "directories": [str(self.instance), str(self.instance / "volumes")],
            "mode": "0755",
            "instance": str(self.instance),
            "pending_marker": str(self.marker),
            "running_check": True,
        }
        args.update(overrides)
        return args

    def _run(self, args, *, check_mode=False, diff=False, path=None):
        buffer = io.StringIO()
        module_args = {**args, "_ansible_check_mode": check_mode, "_ansible_diff": diff}
        with (
            mock.patch.dict(os.environ, {"PATH": str(path or self.bin)}),
            patch_module_args(module_args),
            contextlib.redirect_stdout(buffer),
            self.assertRaises(SystemExit),
        ):
            _MOD.main()
        return json.loads(buffer.getvalue())

    def _recorded(self):
        return self.record.read_text(  # nocheck: cache-read tempdir record the fake compose rewrites on every call
            encoding="utf-8"
        ).splitlines()

    def test_creates_missing_directories_with_the_mode(self):
        result = self._run(self._args())
        self.assertTrue(result["changed"])
        self.assertEqual(
            result["changed_paths"],
            [str(self.instance), str(self.instance / "volumes")],
        )
        self.assertEqual(stat.S_IMODE(self.instance.stat().st_mode), 0o755)

    def test_existing_directories_are_unchanged(self):
        self._run(self._args())
        result = self._run(self._args())
        self.assertFalse(result["changed"])
        self.assertEqual(result["changed_paths"], [])

    def test_probe_never_reports_changed_on_its_own(self):
        self._run(self._args())
        self.marker.write_text("", encoding="utf-8")
        result = self._run(self._args())
        self.assertFalse(result["changed"])

    def test_pending_is_true_when_the_marker_exists(self):
        self.instance.mkdir(parents=True)
        self.marker.write_text("", encoding="utf-8")
        self.assertTrue(self._run(self._args())["pending"])

    def test_pending_is_false_without_the_marker(self):
        self.assertFalse(self._run(self._args())["pending"])

    def test_pending_counts_a_dangling_symlink_like_stat(self):
        self.instance.mkdir(parents=True)
        self.marker.symlink_to(self.root / "gone")
        self.assertTrue(self._run(self._args())["pending"])

    def test_running_reports_compose_ps_output_without_trailing_newlines(self):
        self._fake_compose(stdout="abc\\ndef\\n", stderr="warn\\n", rc=0)
        running = self._run(self._args())["running"]
        self.assertEqual(running, {"rc": 0, "stdout": "abc\ndef", "stderr": "warn"})

    def test_running_runs_ps_with_the_running_filter_in_the_instance(self):
        self._run(self._args())
        self.assertEqual(
            self._recorded(),
            [str(self.instance), "ps", "-q", "--filter", "status=running"],
        )

    def test_running_reports_a_failing_ps_without_failing_the_module(self):
        self._fake_compose(stdout="", stderr="no configuration file provided", rc=1)
        result = self._run(self._args())
        self.assertNotIn("failed", result)
        self.assertEqual(result["running"]["rc"], 1)
        self.assertEqual(result["running"]["stderr"], "no configuration file provided")

    def test_running_is_null_and_ps_skipped_without_running_check(self):
        result = self._run(self._args(running_check=False))
        self.assertIsNone(result["running"])
        self.assertFalse(self.record.exists())

    def test_pending_is_reported_without_running_check(self):
        self.instance.mkdir(parents=True)
        self.marker.write_text("", encoding="utf-8")
        self.assertTrue(self._run(self._args(running_check=False))["pending"])

    def test_check_mode_creates_nothing_and_skips_ps(self):
        result = self._run(self._args(), check_mode=True)
        self.assertTrue(result["changed"])
        self.assertIsNone(result["running"])
        self.assertFalse(self.instance.exists())
        self.assertFalse(self.record.exists())

    def test_directory_failure_fails_before_ps(self):
        self.instance.parent.mkdir(parents=True)
        self.instance.write_text("", encoding="utf-8")
        result = self._run(self._args())
        self.assertTrue(result["failed"])
        self.assertIn("already exists as a file", result["msg"])
        self.assertFalse(self.record.exists())

    def test_missing_compose_fails_loudly(self):
        empty = self.root / "empty"
        empty.mkdir()
        result = self._run(self._args(), path=empty)
        self.assertTrue(result["failed"])
        self.assertIn("compose", result["msg"])

    def test_missing_compose_is_irrelevant_without_running_check(self):
        empty = self.root / "empty"
        empty.mkdir()
        result = self._run(self._args(running_check=False), path=empty)
        self.assertNotIn("failed", result)

    def test_diff_mode_lists_each_created_directory(self):
        result = self._run(self._args(), diff=True)
        self.assertEqual(len(result["diff"]), 2)
        self.assertEqual(result["diff"][0]["after"]["state"], "directory")

    def test_running_check_is_required(self):
        args = self._args()
        del args["running_check"]
        result = self._run(args)
        self.assertTrue(result["failed"])
        self.assertIn("running_check", result["msg"])


if __name__ == "__main__":
    unittest.main()
