import contextlib
import importlib.util
import io
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase, main

from . import PROJECT_ROOT

SCRIPT_PATH = (
    PROJECT_ROOT
    / "roles"
    / "svc-bkp-volume-2-local"
    / "files"
    / "python"
    / "baudolo"
    / "maintenance.py"
)


def load_target_module():
    spec = importlib.util.spec_from_file_location("baudolo_maintenance", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SCRIPT = load_target_module()
NOW = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)


class TestCommandLine(TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.document = Path(self.scratch.name) / "maintenance" / "backup.json"

    def active(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            SCRIPT.main(["active", "--file", str(self.document)])
        return json.loads(out.getvalue())

    def test_announce_creates_the_directory_and_lists_the_applications(self):
        SCRIPT.main(
            [
                "announce",
                "--file",
                str(self.document),
                "--seconds",
                "3600",
                "--application",
                "web-svc-seaweedfs",
                "--application",
                "web-app-openbao",
            ]
        )
        self.assertEqual(self.active(), ["web-app-openbao", "web-svc-seaweedfs"])
        self.assertEqual(self.document.stat().st_mode & 0o777, 0o644)

    def test_clear_keeps_the_window_and_empties_the_list(self):
        announced = SCRIPT.announce(self.document, ["web-app-openbao"], 3600, NOW)
        SCRIPT.main(["clear", "--file", str(self.document)])
        cleared = json.loads(
            self.document.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        )
        self.assertEqual(cleared["applications"], [])
        self.assertEqual(cleared["started"], announced["started"])
        self.assertEqual(cleared["until"], announced["until"])

    def test_active_reports_nothing_without_a_document(self):
        self.assertEqual(self.active(), [])

    def test_the_write_leaves_no_staged_file_behind(self):
        SCRIPT.announce(self.document, ["web-app-openbao"], 60, NOW)
        SCRIPT.clear(self.document, NOW + timedelta(seconds=30))
        self.assertEqual(
            sorted(p.name for p in self.document.parent.iterdir()), ["backup.json"]
        )

    def test_an_invalid_document_is_never_written(self):
        with self.assertRaises(ValueError):
            SCRIPT.write(self.document, {"applications": [], "started": "x"})
        self.assertFalse(self.document.exists())


if __name__ == "__main__":
    main()
