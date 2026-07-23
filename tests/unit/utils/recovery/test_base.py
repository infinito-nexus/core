from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.recovery.base import DirectoryRecovery


class _Recovery(DirectoryRecovery):
    unit_pattern = "svc-bkp-test*.service"


class TestDirectoryRecovery(unittest.TestCase):
    def _mk(self, td: str) -> tuple[Path, Path]:
        root = Path(td)
        source = root / "source"
        target = root / "target"
        source.mkdir()
        target.mkdir()
        (source / "restored.txt").write_text("from-snapshot")
        (target / "live.txt").write_text("pre-recover")
        return source, target

    def test_run_starts_backup_unit_then_mirrors_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source, target = self._mk(td)
            recovery = _Recovery(str(source), str(target))
            calls: list[list[str]] = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                result = mock.Mock()
                if cmd[:2] == ["systemctl", "list-unit-files"]:
                    result.stdout = "svc-bkp-test.1.example.service enabled\n"
                    return result
                if cmd[:2] == ["systemctl", "start"]:
                    return result
                return mock.DEFAULT

            with mock.patch(
                "utils.recovery.base.subprocess.run", side_effect=fake_run
            ) as run:
                run.side_effect = fake_run
                recovery.backup_target()

            self.assertEqual(
                calls[1], ["systemctl", "start", "svc-bkp-test.1.example.service"]
            )

            recovery.restore()
            restored = target / "restored.txt"
            text = restored.read_text()  # nocheck: cache-read - tempdir fixture
            self.assertEqual(text, "from-snapshot")
            self.assertFalse((target / "live.txt").exists())

    def test_missing_unit_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source, target = self._mk(td)
            recovery = _Recovery(str(source), str(target))

            def fake_run(cmd, **kwargs):
                result = mock.Mock()
                result.stdout = ""
                return result

            with (
                mock.patch("utils.recovery.base.subprocess.run", side_effect=fake_run),
                self.assertRaises(SystemExit),
            ):
                recovery.backup_target()

    def test_no_safety_backup_skips_unit_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source, target = self._mk(td)
            recovery = _Recovery(str(source), str(target), service_backup=False)
            with mock.patch.object(recovery, "backup_target") as backup:
                recovery.run()
            backup.assert_not_called()
            restored = target / "restored.txt"
            text = restored.read_text()  # nocheck: cache-read - tempdir fixture
            self.assertEqual(text, "from-snapshot")

    def test_missing_target_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source, target = self._mk(td)
            with self.assertRaises(SystemExit):
                _Recovery(str(source), str(target / "absent"))

    def test_unit_pattern_is_mandatory(self) -> None:
        class _NoUnit(DirectoryRecovery):
            pass

        with tempfile.TemporaryDirectory() as td:
            source, target = self._mk(td)
            with self.assertRaises(ValueError):
                _NoUnit(str(source), str(target))


if __name__ == "__main__":
    unittest.main()
