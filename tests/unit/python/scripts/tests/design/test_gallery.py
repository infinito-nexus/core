from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

SCRIPT = PROJECT_ROOT / "scripts" / "tests" / "design" / "gallery.sh"
APP = "web-app-gallery-stub"

LOAD_SH = (
    'export PYTHON="${STUB_BIN}/python"\n'
    "export INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR=/reports\n"
)
CONTAINER_SH = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "${cmd}" >>"${STUB_LOG}"\n'
    'if [[ "${cmd}" == tar* ]]; then tar -C "${STUB_SHOTS}" -cf - .; fi\n'
)
PYTHON_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "python %s\\n" "$*" >>"${STUB_LOG}"\n'
    '[[ "$4" =~ ^[a-z0-9-]+$ ]] || exit 2\n'
    'printf "%s/%s\\n" "${STUB_ROOT}" "$4"\n'
)


def _place(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


class TestGalleryScript(unittest.TestCase):
    script = SCRIPT

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.tree = root / "tree"
        self.log = root / "calls.log"
        self.gallery_root = root / "gallery"
        shots = root / "shots" / "after"
        shots.mkdir(parents=True)
        (shots / "home-light-desktop.png").write_bytes(b"\x89PNG")
        script = self.tree / "scripts" / "tests" / "design" / "gallery.sh"
        script.parent.mkdir(parents=True)
        shutil.copy2(self.script, script)
        _place(self.tree / "scripts" / "meta" / "env" / "load.sh", LOAD_SH)
        _place(
            self.tree
            / "scripts"
            / "tests"
            / "deploy"
            / "local"
            / "exec"
            / "container.sh",
            CONTAINER_SH,
        )
        _place(root / "bin" / "python", PYTHON_STUB)
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"BASH_ENV", "ENV", "PYTHON"}
            and not key.startswith("INFINITO_")
        }
        self.env.update(
            STUB_BIN=str(root / "bin"),
            STUB_LOG=str(self.log),
            STUB_ROOT=str(self.gallery_root),
            STUB_SHOTS=str(root / "shots"),
        )

    def _gallery(self, app: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.tree / "scripts" / "tests" / "design" / "gallery.sh")],
            env={**self.env, "app": app},
            capture_output=True,
            text=True,
            check=False,
        )

    def _calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return read_text(str(self.log)).splitlines()

    def test_screenshots_land_in_the_gallery_the_shared_cli_names(self) -> None:
        result = self._gallery(APP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"python -m cli.meta.roles.design.gallery path {APP}", self._calls()
        )
        self.assertTrue(
            (self.gallery_root / APP / "after" / "home-light-desktop.png").is_file()
        )
        self.assertEqual(
            result.stdout.splitlines()[-1], f"screenshots: {self.gallery_root / APP}"
        )

    def test_a_refused_application_id_stops_before_any_container_command(self) -> None:
        result = self._gallery("../escape")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            [call for call in self._calls() if not call.startswith("python ")], []
        )

    def test_the_gallery_root_has_one_source(self) -> None:
        self.assertNotIn("/tmp/design-gallery", read_text(str(self.script)))


if __name__ == "__main__":
    unittest.main()
