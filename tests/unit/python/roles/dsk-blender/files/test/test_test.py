from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/dsk-blender/files/test/test.sh"
APP = "org.blender.Blender"
MODULE = "blender_mcp_addon"
DENIED = "bwrap: Creating new namespace failed: Permission denied"


def _executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)
    return path


class TestSavedPreferencesCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.root / "home" / "alice"
        self.home.mkdir(parents=True)
        self.bin = self.root / "usr" / "local" / "bin"
        self.stage = self.root / "stage"
        self.stage.mkdir()
        shutil.copy(SCRIPT, self.stage / "test.sh")
        (self.stage / "initialize.py").write_text("print('stub')\n")
        self.probe = self.root / "flatpak.argv"
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "BONSAI_EXPECTED": "false",
            "BONSAI_EXTENSION_ID": "",
            "MCP_ADDON_MODULE": MODULE,
            "MCP_CLAUDE_EXPECTED": "false",
            "MCP_CLAUDE_REGISTRY": str(self.home / ".claude.json"),
            "MCP_CODEX_EXPECTED": "false",
            "MCP_CODE_BINARY": "",
            "MCP_CODE_EXPECTED": "false",
            "MCP_SERVER_COMMAND": str(_executable(self.bin / "blender-mcp", "exit 0")),
            "MCP_SERVER_NAME": "blender",
            "MCP_USER_HOME": str(self.home),
        }

    def _native(self) -> None:
        _executable(self.bin / "blender", "exit 0")

    def _flathub(self, rc: int, stderr: str = "") -> None:
        deploy = self.root / "var/lib/flatpak/app" / APP / "x86_64/stable/5e1c0ffee"
        launcher = _executable(deploy / "export/bin" / APP, "exit 0")
        (self.bin / "blender").symlink_to(launcher)
        _executable(
            self.bin / "flatpak",
            f'printf "%s\\n" "$PWD" "$HOME" "$@" > "{self.probe}"\n'
            f'echo "{stderr}" >&2\nexit {rc}',
        )

    def _userpref(self, config_root: Path, content: str = MODULE) -> None:
        prefs = config_root / "5.2" / "config"
        prefs.mkdir(parents=True)
        (prefs / "userpref.blend").write_text(f"BLENDER\0{content}\0")

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.stage / "test.sh")],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_native_blender_reads_the_xdg_config(self) -> None:
        self._native()
        self._userpref(self.home / ".config/blender")
        run = self._run()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("SKIP", run.stdout)

    def test_native_blender_without_the_module_fails(self) -> None:
        self._native()
        self._userpref(self.home / ".config/blender", content="other_addon")
        self.assertNotEqual(self._run().returncode, 0)

    def test_flathub_blender_reads_its_var_app_config(self) -> None:
        self._flathub(rc=0)
        self._userpref(self.home / ".var/app" / APP / "config/blender")
        run = self._run()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("SKIP", run.stdout)
        self.assertEqual(
            self.probe.read_text().splitlines(),
            [str(self.home), str(self.home), "run", "--command=true", APP],
        )

    def test_flathub_blender_ignores_the_native_config(self) -> None:
        self._flathub(rc=0)
        self._userpref(self.home / ".config/blender")
        self.assertNotEqual(self._run().returncode, 0)

    def test_refused_sandbox_reports_the_enable_check_as_skip(self) -> None:
        self._flathub(rc=1, stderr=DENIED)
        run = self._run()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"SKIP: {APP} cannot start its Flatpak sandbox", run.stdout)
        self.assertIn(f"flatpak exited 1: {DENIED}", run.stdout)

    def test_refused_sandbox_keeps_every_other_check(self) -> None:
        self._flathub(rc=1, stderr=DENIED)
        self.env["MCP_CLAUDE_EXPECTED"] = "true"
        (self.home / ".claude.json").write_text("{}")
        run = self._run()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("SKIP:", run.stdout)
        self.assertIn("claude carries the server", run.stdout)


if __name__ == "__main__":
    unittest.main()
