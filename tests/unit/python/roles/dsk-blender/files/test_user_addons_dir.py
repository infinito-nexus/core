from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shlex
import subprocess
import tempfile
import unittest.mock
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/dsk-blender/files/python/user_addons_dir.py"
APP = "org.blender.Blender"
COMMIT = "5e1c0ffee"
DENIED = "bwrap: Creating new namespace failed: Permission denied"


def _load():
    spec = importlib.util.spec_from_file_location("user_addons_dir", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


user_addons_dir = _load()


class _Host:
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.root / "home" / "alice"
        self.bin = self.root / "usr" / "local" / "bin"
        self.bin.mkdir(parents=True)
        self.enterContext(unittest.mock.patch.dict(os.environ, {"PATH": str(self.bin)}))
        self.popen = self.enterContext(
            unittest.mock.patch.object(subprocess, "Popen", wraps=subprocess.Popen)
        )

    def _launcher(self, path: Path, stdout: str, stderr: str, rc: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "#!/bin/sh\n"
            f"printf %s {shlex.quote(stdout)}\n"
            f"printf %s {shlex.quote(stderr)} >&2\n"
            f"exit {rc}\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def install_flathub(self, *versions: str) -> None:
        installation = self.root / "var" / "lib" / "flatpak"
        app_dir = installation / "app" / APP
        deploy = app_dir / "x86_64" / "stable" / COMMIT
        self._launcher(deploy / "export" / "bin" / APP, "", DENIED, 1)
        for version in versions:
            (deploy / "files" / "blender" / version / "datafiles").mkdir(parents=True)
        (deploy / "files" / "blender" / "lib").mkdir(parents=True, exist_ok=True)
        (app_dir / "current").symlink_to("x86_64/stable")
        (deploy.parent / "active").symlink_to(COMMIT)
        exports = installation / "exports" / "bin"
        exports.mkdir(parents=True)
        (exports / APP).symlink_to(f"../../app/{APP}/current/active/export/bin/{APP}")
        (self.bin / "blender").symlink_to(exports / APP)

    def install_native(self, stdout: str, stderr: str = "", rc: int = 0) -> None:
        self._launcher(self.root / "usr" / "bin" / "blender", stdout, stderr, rc)
        (self.bin / "blender").symlink_to(self.root / "usr" / "bin" / "blender")

    def started(self) -> list[list[str]]:
        return [list(call.args[0]) for call in self.popen.call_args_list]


class TestFlathubBlender(_Host, unittest.TestCase):
    def test_the_directory_sits_in_the_app_config_under_the_archive_version(self):
        self.install_flathub("5.3")
        self.assertEqual(
            user_addons_dir.addons_dir("blender", self.home),
            self.home
            / ".var/app/org.blender.Blender/config/blender/5.3/scripts/addons",
        )

    def test_the_sandboxed_launcher_is_never_started(self):
        self.install_flathub("5.3")
        user_addons_dir.addons_dir("blender", self.home)
        self.assertEqual(
            self.started(),
            [],
            f"starting the Flathub launcher needs a user namespace, which the "
            f"CI runner refuses ({DENIED}, run 43828138456 Blender#0)",
        )

    def test_a_deploy_without_a_version_directory_is_refused(self):
        self.install_flathub()
        with self.assertRaises(user_addons_dir.UnresolvedError):
            user_addons_dir.addons_dir("blender", self.home)

    def test_a_deploy_with_two_version_directories_is_refused(self):
        self.install_flathub("5.2", "5.3")
        with self.assertRaises(user_addons_dir.UnresolvedError):
            user_addons_dir.addons_dir("blender", self.home)


class TestDistributionBlender(_Host, unittest.TestCase):
    def test_blender_names_the_directory_itself(self):
        named = "/home/alice/.config/blender/4.3/scripts/addons"
        self.install_native(f"Blender 4.3.2\nADDONS={named}\n\nBlender quit\n")
        self.assertEqual(user_addons_dir.addons_dir("blender", self.home), Path(named))

    def test_blender_runs_in_background_mode(self):
        self.install_native("ADDONS=/home/alice/.config/blender/4.3/scripts/addons\n")
        user_addons_dir.addons_dir("blender", self.home)
        self.assertEqual(len(self.started()), 1)
        self.assertEqual(self.started()[0][1:3], ["--background", "--python-expr"])

    def test_a_failing_blender_is_reported_with_its_stderr(self):
        self.install_native("", stderr="cannot open display", rc=1)
        with self.assertRaisesRegex(
            user_addons_dir.UnresolvedError, "cannot open display"
        ):
            user_addons_dir.addons_dir("blender", self.home)

    def test_output_without_the_marker_is_refused(self):
        self.install_native("Blender 4.3.2\n\nBlender quit\n")
        with self.assertRaises(user_addons_dir.UnresolvedError):
            user_addons_dir.addons_dir("blender", self.home)


class TestMain(_Host, unittest.TestCase):
    def test_a_missing_launcher_exits_one_with_the_reason(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = user_addons_dir.main(["user_addons_dir.py", "blender"])
        self.assertEqual(rc, 1)
        self.assertIn("blender is not on PATH", stderr.getvalue())

    def test_the_directory_is_the_only_stdout(self):
        self.install_flathub("5.3")
        stdout = io.StringIO()
        with (
            unittest.mock.patch.object(Path, "home", return_value=self.home),
            contextlib.redirect_stdout(stdout),
        ):
            rc = user_addons_dir.main(["user_addons_dir.py", "blender"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            stdout.getvalue(),
            f"{self.home}/.var/app/org.blender.Blender/config/blender/5.3/scripts/addons\n",
        )


if __name__ == "__main__":
    unittest.main()
