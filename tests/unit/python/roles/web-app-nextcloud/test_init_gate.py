from __future__ import annotations

import fcntl
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.cache.files import PROJECT_ROOT, read_text

GATE = read_text(
    str(PROJECT_ROOT / "roles/web-app-nextcloud/files/shell/utils/init-gate.sh")
)
APP_DIR_LINE = 'APP_DIR="/var/www/html"'
UPSTREAM_EXEC = "exec /entrypoint.sh"
HANDED_OVER = "upstream entrypoint reached"
INIT_LOCK = "nextcloud-init-sync.lock"
COPIED = ("version.php", "occ", "config/config.php")
STUB_SU = "#!/bin/sh\nprintf '%s\\n' \"$GATE_STATUS\"\n"
INSTALLED = "  - installed: true\n  - maintenance: false\n  - needsDbUpgrade: false"
NOT_INSTALLED = (
    "  - installed: false\n  - maintenance: false\n  - needsDbUpgrade: false"
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run_gate(
    *,
    task_slot: str | None,
    files: tuple[str, ...],
    status: str,
    hold_init_lock: bool,
) -> subprocess.CompletedProcess:
    """Run the gate as slot 1 against a fake app dir.

    Args:
        task_slot: value of TASK_SLOT, or None to leave it unset as compose does.
        files: paths relative to the app dir that exist before the gate runs.
        status: what `occ status` prints through the stubbed `su`.
        hold_init_lock: hold the upstream init lock while the gate runs, as an
            entrypoint that is still copying or installing does.
    """
    assert GATE.count(APP_DIR_LINE) == 1, "the gate no longer pins APP_DIR"
    assert GATE.count(UPSTREAM_EXEC) == 1, "the gate no longer execs upstream"
    with TemporaryDirectory() as directory:
        root = Path(directory)
        app_dir = root / "html"
        (app_dir / "config").mkdir(parents=True)
        for relative in files:
            (app_dir / relative).write_text("", encoding="utf-8")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        _write_executable(bin_dir / "su", STUB_SU)
        entrypoint = root / "entrypoint.sh"
        _write_executable(entrypoint, f"#!/bin/sh\necho {HANDED_OVER}\n")
        gate = root / "init-gate.sh"
        gate.write_text(
            GATE.replace(APP_DIR_LINE, f'APP_DIR="{app_dir}"').replace(
                UPSTREAM_EXEC, f"exec {entrypoint}"
            ),
            encoding="utf-8",
        )
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "NEXTCLOUD_INIT_GATE_USER": "www-data",
            "GATE_STATUS": status,
        }
        if task_slot is not None:
            env["TASK_SLOT"] = task_slot
        with (app_dir / INIT_LOCK).open("w", encoding="utf-8") as lock:
            if hold_init_lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
            return subprocess.run(
                ["sh", str(gate), "php-fpm"],
                check=False,
                capture_output=True,
                env=env,
                text=True,
                timeout=30,
            )


class TestInitGateSlotOne(unittest.TestCase):
    def test_refuses_an_install_that_failed_after_the_copy(self):
        for task_slot in (None, "1"):
            with self.subTest(task_slot=task_slot):
                result = _run_gate(
                    task_slot=task_slot,
                    files=COPIED,
                    status=NOT_INSTALLED,
                    hold_init_lock=False,
                )
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertNotIn(HANDED_OVER, result.stdout)
                self.assertIn("installed: false", result.stderr)

    def test_refuses_a_copy_without_any_config(self):
        result = _run_gate(
            task_slot="1",
            files=("version.php", "occ"),
            status=NOT_INSTALLED,
            hold_init_lock=False,
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn(HANDED_OVER, result.stdout)

    def test_leaves_a_running_install_to_the_upstream_lock(self):
        result = _run_gate(
            task_slot="1", files=COPIED, status=NOT_INSTALLED, hold_init_lock=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(HANDED_OVER, result.stdout)

    def test_hands_an_installed_volume_to_upstream(self):
        result = _run_gate(
            task_slot="1", files=COPIED, status=INSTALLED, hold_init_lock=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(HANDED_OVER, result.stdout)

    def test_hands_a_fresh_volume_to_upstream_for_the_install(self):
        result = _run_gate(
            task_slot=None, files=(), status=NOT_INSTALLED, hold_init_lock=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(HANDED_OVER, result.stdout)

    def test_hands_over_when_occ_status_answers_nothing(self):
        result = _run_gate(task_slot="1", files=COPIED, status="", hold_init_lock=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(HANDED_OVER, result.stdout)


if __name__ == "__main__":
    unittest.main()
